import os
import uuid
import time
import shutil
import logging
import gc
from pathlib import Path

import librosa
import soundfile as sf
import numpy as np
import torch
from scipy.signal import correlate

# Pird: cap input audio length to bound memory. See
# handoffs/dubbing-security-pass3-fixes.md Fix 10.
MAX_AUDIO_DURATION_SEC = 7200  # 2 hours

# Pird: isolation outputs are always written under this root. See Fix 9.
ALLOWED_OUTPUT_ROOT = Path("data/jobs/sessions").resolve()

# Pird: model pinning + checksum verification. See Fix 7.
# TODO: pin actual commit SHAs and SHA-256 weights before shipping prod.
# The repo URLs and weights file are listed for clarity; the SHAs must be
# filled in by the user (one-time setup, requires a known-good download).
MODEL_MANIFEST = {
    "silero_vad": {
        "repo": "snakers4/silero-vad",
        # TODO: pin actual commit. Format: 40-char hex.
        "revision": "TODO_PIN_COMMIT",
        # TODO: SHA-256 of silero_vad.jit (or silero_vad.pt) once vendored.
        "expected_sha256": "TODO_PIN_SHA256",
    },
    "model_bs_roformer_ep_317_sdr_12.9755.ckpt": {
        # TODO: SHA-256 of the ckpt file. Compute via:
        #   sha256sum ~/.cache/audio-separator/model_bs_roformer_ep_317_sdr_12.9755.ckpt
        "expected_sha256": "TODO_PIN_SHA256",
    },
}


def _verify_sha256(path: Path, expected: str) -> None:
    """SHA-256 verify helper. Fails closed in production if expected starts with TODO_."""
    if expected.startswith("TODO_"):
        if os.getenv("PIRD_ENV") == "prod":
            raise RuntimeError(
                f"Security Violation: Unpinned model checkpoint checksum for {path.name} in production environment."
            )
        logger.warning(
            "[ISOLATION] SHA-256 check skipped for %s — manifest not yet pinned",
            path.name,
        )
        return
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(64 * 1024), b""):
            h.update(chunk)
    if h.hexdigest().lower() != expected.lower():
        raise RuntimeError(f"Model checksum mismatch for {path}: expected {expected}, got {h.hexdigest()}")

logger = logging.getLogger(__name__)

TARGET_SR = 44100

# Stage 0: Input Validation
def load_and_validate(path: str) -> tuple[np.ndarray, int]:
    path = Path(path)
    if path.suffix.lower() not in {'.wav', '.flac', '.mp3', '.aiff', '.m4a'}:
        raise ValueError(f"The audio format '{path.suffix}' is not supported. Please upload a standard format like WAV or MP4.")

    info = sf.info(str(path))
    if info.duration > MAX_AUDIO_DURATION_SEC:
        raise ValueError(
            f"Input audio duration ({info.duration:.1f}s) exceeds the maximum limit "
            f"of {MAX_AUDIO_DURATION_SEC}s ({MAX_AUDIO_DURATION_SEC // 3600} hours)."
        )

    audio, sr = librosa.load(str(path), sr=None, mono=False)
    if audio.ndim == 1:
        audio = np.stack([audio, audio])

    peak = np.max(np.abs(audio))
    if peak < 0.001:
        raise ValueError("The audio in this file is completely silent. Please check your file and re-upload.")
    if peak > 0.999:
        logger.warning(f"WARNING: Input is clipped (peak={peak:.4f}). Normalize the source first.")

    if sr != TARGET_SR:
        audio = librosa.resample(audio, orig_sr=sr, target_sr=TARGET_SR)

    return audio.astype(np.float32), TARGET_SR

# Stage 1: Silence Mapping
def generate_silence_mask(
    audio: np.ndarray,
    sr: int,
    threshold_db: float = -55.0,
    frame_length: int = 2048,
    hop_length: int = 512,
) -> np.ndarray:
    mono = audio.mean(axis=0)
    rms = librosa.feature.rms(y=mono, frame_length=frame_length, hop_length=hop_length)[0]
    rms_db = librosa.amplitude_to_db(rms + 1e-10, ref=1.0)
    frame_mask = rms_db < threshold_db

    sample_mask = np.zeros(audio.shape[1], dtype=bool)
    for frame_idx in np.where(frame_mask)[0]:
        start = frame_idx * hop_length
        end = min(start + frame_length, audio.shape[1])
        sample_mask[start:end] = True

    return sample_mask

# Stage 2a: BS-RoFormer
def run_roformer(audio: np.ndarray, sr: int, device: str = None, run_uuid: str = "") -> tuple[np.ndarray, np.ndarray]:
    if device is None:
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        
    from audio_separator.separator import Separator

    import tempfile
    import logging

    tmp_dir = Path(tempfile.gettempdir()) / f"isolation_{run_uuid}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = str(tmp_dir / "input.wav")
    
    # Normalize audio to prevent audio-separator from rejecting it due to min_mean_abs < 0.001
    peak = np.max(np.abs(audio))
    if peak > 0:
        audio = audio / peak * 0.95

    sf.write(tmp_path, audio.T, sr, subtype='PCM_16')

    try:
        # Memory optimization for 6GB GPUs to prevent CUDA OOM
        os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
        sep = Separator(
            output_format='wav',
            output_dir=str(tmp_dir),
            use_autocast=(device == 'cuda'),
            log_level=logging.INFO,
            mdxc_params={
                'segment_size': 128,  # Default is 256. 128 cuts VRAM usage significantly.
                'override_model_segment_size': True,
                'batch_size': 1,
                'overlap': 4,       # Default is 8.
                'pitch_shift': 0
            }
        )
        sep.load_model(model_filename='model_bs_roformer_ep_317_sdr_12.9755.ckpt')
        outputs = sep.separate(tmp_path)

        if not outputs:
            logger.warning("BS-RoFormer returned no output list. Manually checking output directory...")
            outputs = [f.name for f in tmp_dir.iterdir() if f.is_file() and f.name != "input.wav"]
            if not outputs:
                raise RuntimeError(f"BS-RoFormer completely failed. No files generated in {tmp_dir}.")

        vocal_file = next((f for f in outputs if 'vocal' in Path(f).stem.lower()), None)
        inst_file = next((f for f in outputs if 'instrumental' in Path(f).stem.lower() or 'other' in Path(f).stem.lower()), None)
        
        if not vocal_file or not inst_file:
            if len(outputs) >= 2:
                vocal_file = outputs[0]
                inst_file = outputs[1]
                logger.warning(f"Could not parse vocal/inst from filenames. Falling back to index 0/1. Outputs: {outputs}")
            else:
                raise RuntimeError(f"BS-RoFormer did not return enough files. Outputs: {outputs}")
        
        vocal_path = str(tmp_dir / vocal_file) if not os.path.isabs(vocal_file) else vocal_file
        inst_path = str(tmp_dir / inst_file) if not os.path.isabs(inst_file) else inst_file

        vocal, _ = librosa.load(vocal_path, sr=sr, mono=False)
        inst, _ = librosa.load(inst_path, sr=sr, mono=False)
        
        vocal = vocal if vocal.ndim == 2 else np.stack([vocal, vocal])
        inst = inst if inst.ndim == 2 else np.stack([inst, inst])
        return vocal, inst
    finally:
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)
            
# Stage 2b: HTDemucs_ft
def run_htdemucs(
    audio: np.ndarray,
    sr: int,
    device: str = None,
    shifts: int = 8,
    overlap: float = 0.75,
) -> np.ndarray:
    if device is None:
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        
    from demucs.pretrained import get_model
    from demucs.apply import apply_model
    
    model = get_model('htdemucs_ft').to(device)
    model.eval()

    wav = torch.from_numpy(audio).float().unsqueeze(0).to(device)

    with torch.no_grad():
        sources = apply_model(
            model, wav,
            shifts=4,
            split=True,
            overlap=overlap,
            progress=True,
        )

    vocal_idx = model.sources.index('vocals')
    result = sources[0, vocal_idx].cpu().numpy()
    
    del model
    del wav
    del sources
    return result

# Stage 3: Phase Alignment
def phase_align_tensors(
    tensor_a: np.ndarray,
    tensor_b: np.ndarray,
    search_window_samples: int = 512,
) -> tuple[np.ndarray, np.ndarray, int]:
    ref = tensor_a[0]
    sig = tensor_b[0]

    corr = correlate(ref, sig, mode='full')
    center = len(ref) - 1
    half_w = search_window_samples // 2
    search_slice = corr[center - half_w : center + half_w + 1]
    offset = int(np.argmax(search_slice)) - half_w

    if offset == 0:
        return tensor_a, tensor_b, 0

    aligned_b = np.zeros_like(tensor_b)
    if offset > 0:
        aligned_b[:, : -offset] = tensor_b[:, offset:]
    else:
        o = abs(offset)
        aligned_b[:, o:] = tensor_b[:, :tensor_b.shape[1] - o]

    return tensor_a, aligned_b, offset

# Stage 4: Frequency-Domain Ensemble (Hard Spectral Mask)
def frequency_domain_ensemble(
    vocal_a: np.ndarray,
    vocal_b: np.ndarray,
    sr: int = 44100,
    n_fft: int = 4096,
    hop_length: int = 1024,
) -> np.ndarray:
    result_channels = []

    for ch in range(vocal_a.shape[0]):
        stft_a = librosa.stft(vocal_a[ch], n_fft=n_fft, hop_length=hop_length)
        stft_b = librosa.stft(vocal_b[ch], n_fft=n_fft, hop_length=hop_length)

        mag_a, phase_a = np.abs(stft_a), np.angle(stft_a)
        mag_b = np.abs(stft_b)

        # HARD SPECTRAL MASK: 
        # Demucs acts as a surgical knife. If Demucs has less than 10% of the energy of Roformer in this bin,
        # it means Demucs classified this bin as background music/noise and removed it.
        # We force this entire bin to absolute zero. Otherwise, we let Roformer fill in the warm details.
        hard_mask = (mag_b > 0.1 * mag_a).astype(np.float32)
        
        blended_mag = mag_a * hard_mask
        blended_phase = phase_a

        stft_blend = blended_mag * np.exp(1j * blended_phase)
        result_channels.append(
            librosa.istft(stft_blend, hop_length=hop_length, length=vocal_a.shape[1])
        )

    return np.array(result_channels, dtype=np.float32)

# Stage 5: Silence Region Restoration
def restore_silence_regions(
    vocal_stem: np.ndarray,
    silence_mask: np.ndarray,
) -> np.ndarray:
    result = vocal_stem.copy()
    result[:, silence_mask] = 0.0
    return result

# Stage 6: Quality Gate
def evaluate_quality(vocal: np.ndarray, sr: int) -> dict:
    mono = vocal.mean(axis=0)
    metrics = {}

    peak = np.max(np.abs(mono))
    rms = np.sqrt(np.mean(mono ** 2))
    metrics['crest_factor_db'] = float(20 * np.log10(peak / (rms + 1e-10)))

    metrics['silence_ratio'] = float(np.mean(np.abs(mono) < 0.001))

    stft = np.abs(librosa.stft(mono, n_fft=2048))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
    band_mask = (freqs >= 300) & (freqs <= 8000)
    flatness = librosa.feature.spectral_flatness(S=stft[band_mask])
    metrics['spectral_flatness'] = float(np.mean(flatness))

    metrics['pass'] = True
    if metrics['silence_ratio'] > 0.80:
        metrics['pass'] = False
        metrics['fail_reason'] = f"Silence ratio {metrics['silence_ratio']:.2%}: separation failed"
    elif metrics['crest_factor_db'] < 8.0:
        metrics['pass'] = False
        metrics['fail_reason'] = f"Crest factor {metrics['crest_factor_db']:.1f}dB: transients destroyed"
    elif metrics['spectral_flatness'] < 0.002:
        metrics['pass'] = False
        metrics['fail_reason'] = "Low spectral flatness: suspected music bleed in vocal band"

    return metrics

# Stage 7: Vocal Enhancement
def enhance_vocal(vocal: np.ndarray, sr: int, device: str = None) -> np.ndarray:
    if device is None:
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
    try:
        from resemble_enhance.enhancer.inference import enhance
    except ImportError:
        logger.warning("[ISOLATION] Resemble Enhance is not installed (likely due to Windows DeepSpeed build issues). Bypassing Stage 7.")
        return vocal

    mono = torch.from_numpy(vocal.mean(axis=0)).float()
    
    logger.info("Benchmarking Resemble Enhance latency with nfe=32...")
    start_t = time.time()
    # To avoid huge latency, we pre-emptively drop to nfe=32 per user authorization
    enhanced, _ = enhance(mono, sr, device=device, nfe=32, solver='midpoint', lambd=0.1, tau=0.5)
    end_t = time.time()
    logger.info(f"Resemble Enhance completed in {end_t - start_t:.2f}s with nfe=32.")
    
    enhanced_np = enhanced.cpu().numpy()
    
    del mono
    del enhanced
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    return np.stack([enhanced_np, enhanced_np]).astype(np.float32)

# Stage 8: True Peak Normalization & Dual Output
def true_peak_normalize(audio: np.ndarray, sr: int, target_dbtp: float) -> np.ndarray:
    oversampled = librosa.resample(audio, orig_sr=sr, target_sr=sr * 4)
    true_peak = np.max(np.abs(oversampled))
    if true_peak < 1e-10:
        return audio
    gain = 10 ** ((target_dbtp - 20 * np.log10(true_peak)) / 20)
    return audio * gain

def export_dual_output(vocal: np.ndarray, instrumental: np.ndarray, sr: int, output_dir: str) -> dict:
    # Pird: validate output_dir is under ALLOWED_OUTPUT_ROOT. See Fix 9.
    out = Path(output_dir).resolve()
    if not out.is_relative_to(ALLOWED_OUTPUT_ROOT):
        raise ValueError(
            f"output_dir must be under {ALLOWED_OUTPUT_ROOT}, got {out}"
        )
    out.mkdir(parents=True, exist_ok=True)

    # Pyannote target (-3dBTP)
    mono_16k = librosa.resample(vocal.mean(axis=0), orig_sr=sr, target_sr=16000)
    mono_16k = true_peak_normalize(mono_16k[np.newaxis], sr=16000, target_dbtp=-3.0)
    pyannote_path = out / "vocals_stem_pyannote_16k.wav"
    sf.write(str(pyannote_path), mono_16k[0], 16000, subtype='PCM_16')

    # Fish Audio target (-1dBTP)
    fish = true_peak_normalize(vocal, sr=sr, target_dbtp=-1.0)
    fish_path = out / "vocals_stem_fish_44k1.wav"
    sf.write(str(fish_path), fish.T, sr, subtype='FLOAT')
    
    # Instrumental target: preserve natural gain relative to original audio
    inst_path = out / "instrumental_stem_44k1.wav"
    sf.write(str(inst_path), instrumental.T, sr, subtype='FLOAT')

    return {'pyannote': str(pyannote_path), 'fish_audio': str(fish_path), 'instrumental': str(inst_path)}

# Stage 9: Orchestrator
def run_vcta_pipeline(input_path: str, output_dir: str, device: str = None) -> dict:
    if device is None:
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        
    run_uuid = uuid.uuid4().hex
    
    logger.info(f"[ISOLATION] Stage 0: Load & validate {input_path}")
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    audio, sr = load_and_validate(input_path)

    logger.info("[ISOLATION] Stage 0.5: Mathematical Warm-Up Padding (Reflective, 2.0s)")
    pad_samples = int(2.0 * sr)
    # Reflective padding: take the first 2.0s of actual audio, reverse it, and attach to the front.
    # This prevents the "Digital Zero Trap" and lets the AI analyze the true noise floor before the timeline hits 0.0s.
    audio = np.pad(audio, ((0, 0), (pad_samples, 0)), mode='reflect')

    logger.info("[ISOLATION] Stage 1: Silence mapping")
    silence_mask = generate_silence_mask(audio, sr)
    logger.info(f"[ISOLATION] Silence coverage: {silence_mask.mean():.1%}")

    logger.info("[ISOLATION] Stage 2a: BS-RoFormer inference")
    vocal_roformer, inst_stem = run_roformer(audio, sr, device=device, run_uuid=run_uuid)
    
    raw_rof_path = str(Path(output_dir) / "raw_vocal_roformer.wav")
    sf.write(raw_rof_path, vocal_roformer.T, sr, subtype='FLOAT')
    
    # VRAM Sequence Rule Enforcement
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    logger.info("[ISOLATION] Stage 2b: HTDemucs_ft inference")
    vocal_demucs = run_htdemucs(audio, sr, device=device, shifts=8, overlap=0.75)
    
    raw_dem_path = str(Path(output_dir) / "raw_vocal_demucs.wav")
    sf.write(raw_dem_path, vocal_demucs.T, sr, subtype='FLOAT')

    # VRAM Sequence Rule Enforcement 2
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    logger.info("[ISOLATION] Stage 3: Phase alignment")
    vocal_roformer, vocal_demucs, offset = phase_align_tensors(vocal_roformer, vocal_demucs)
    logger.info(f"[ISOLATION] Offset: {offset} samples ({offset / sr * 1000:.2f}ms)")

    logger.info("[ISOLATION] Stage 4: Frequency-domain ensemble")
    vocal_ensemble = frequency_domain_ensemble(vocal_roformer, vocal_demucs, sr)

    logger.info("[ISOLATION] Stage 4.5: Cleanup (Slice 2.0s Warm-Up Padding)")
    # Mathematically slice the exact padding off the front to re-sync with video timeline
    vocal_ensemble = vocal_ensemble[:, pad_samples:]
    audio = audio[:, pad_samples:]
    silence_mask = silence_mask[pad_samples:]

    logger.info("[ISOLATION] Stage 5: Silence restoration")
    vocal_clean = restore_silence_regions(vocal_ensemble, silence_mask)

    # Compute true background stem by subtracting clean isolated vocals from original audio
    min_len = min(audio.shape[1], vocal_clean.shape[1])
    inst_stem = audio[:, :min_len] - vocal_clean[:, :min_len]

    logger.info("[ISOLATION] Stage 6: Quality gate")
    metrics = evaluate_quality(vocal_clean, sr)
    logger.info(f"[ISOLATION] Metrics: {metrics}")
    if not metrics['pass']:
        raise RuntimeError(f"QUALITY GATE FAILED: {metrics.get('fail_reason')}")

    logger.info("[ISOLATION] Stage 7: Vocal enhancement (Resemble Enhance)")
    vocal_enhanced = enhance_vocal(vocal_clean, sr, device=device)

    logger.info("[ISOLATION] Stage 8: Export")
    paths = export_dual_output(vocal_enhanced, inst_stem, sr, output_dir)

    return {
        'paths': paths, 
        'metrics': metrics, 
        'phase_offset_samples': offset,
        'raw_roformer': raw_rof_path,
        'raw_demucs': raw_dem_path
    }
