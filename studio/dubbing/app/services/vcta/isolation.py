import os
import uuid
import time
import shutil
import logging
import gc
import tempfile
import subprocess
from pathlib import Path

import librosa
import soundfile as sf
import numpy as np
import torch
from pydub import AudioSegment
from audio_separator.separator import Separator
from df.enhance import enhance, init_df, load_audio, save_audio

logger = logging.getLogger(__name__)

MAX_AUDIO_DURATION_SEC = 7200  # 2 hours
ALLOWED_OUTPUT_ROOT = Path("data/jobs/sessions").resolve()
TARGET_SR = 44100


def _verify_sha256(path: Path, expected: str) -> None:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Checkpoint not found: {path}")
    if not expected or expected == "TODO_PIN_SHA256":
        if os.getenv("PIRD_ENV") == "prod":
            raise RuntimeError(f"Security Violation: Unpinned model checkpoint {path.name}")
        logger.warning(f"Unpinned model checkpoint {path.name} loaded in non-production.")
        return

    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(64 * 1024), b""):
            h.update(chunk)
    actual = h.hexdigest()
    if actual != expected:
        raise RuntimeError(f"Security Violation: model checksum mismatch for {path.name}. Expected {expected}, got {actual}")


def load_and_validate(path: str) -> tuple[np.ndarray, int]:
    path = Path(path)
    allowed_exts = {'.wav', '.flac', '.mp3', '.aiff', '.m4a', '.mp4', '.mkv', '.mov', '.webm', '.avi'}
    if path.suffix.lower() not in allowed_exts:
        raise ValueError(f"The format '{path.suffix}' is not supported. Supported formats: {', '.join(sorted(allowed_exts))}.")

    try:
        duration = sf.info(str(path)).duration
    except Exception:
        duration = librosa.get_duration(path=str(path))

    if duration > MAX_AUDIO_DURATION_SEC:
        raise ValueError(
            f"Input audio duration ({duration:.1f}s) exceeds the maximum limit "
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


def restore_silence_regions(vocal_audio: np.ndarray, silence_mask: np.ndarray) -> np.ndarray:
    cleaned = vocal_audio.copy()
    cleaned[:, silence_mask] = 0.0
    return cleaned


def true_peak_normalize(audio: np.ndarray, sr: int, target_dbtp: float = -1.0) -> np.ndarray:
    peak = np.max(np.abs(audio))
    if peak <= 1e-9:
        return audio

    target_linear = 10 ** (target_dbtp / 20.0)
    scale = target_linear / peak
    return audio * scale


def _resample_and_pad_audio(input_path: str, padded_path: str, pad_ms: int = 3000) -> int:
    """
    1. Resamples input audio to 44.1kHz 32-bit float WAV (pcm_f32le) for micro-dynamics accuracy.
    2. Prepends 3s of reversed audio to start and appends 3s to end to eliminate STFT boundary distortion.
    """
    temp_44k = padded_path + ".44k.wav"
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-ar", "44100", "-ac", "2", "-c:a", "pcm_f32le",
        temp_44k
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    audio = AudioSegment.from_file(temp_44k)
    head_pad = audio[:pad_ms].reverse()
    tail_pad = audio[-pad_ms:].reverse()

    padded_audio = head_pad + audio + tail_pad
    padded_audio.export(padded_path, format="wav")

    if os.path.exists(temp_44k):
        try: os.remove(temp_44k)
        except Exception: pass
        
    return pad_ms


def _trim_audio_pads_to_file(src_path: str, dst_path: str, pad_ms: int = 3000):
    """Trims off the 3-second head and tail reflection padding and writes result to dst_path."""
    audio = AudioSegment.from_file(src_path)
    trimmed = audio[pad_ms:-pad_ms]
    trimmed.export(dst_path, format="wav")


def apply_highpass_filter(input_path: str, output_path: str, cutoff_hz: int = 80) -> str:
    """Applies a strict High-Pass Filter using FFmpeg to kill sub-bass rumble."""
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-af", f"highpass=f={cutoff_hz}",
        "-c:a", "pcm_f32le",  # Maintain 32-bit float
        output_path
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return output_path


def execute_speech_enhancement(pass1_vocal_path: str, final_vocal_path: str) -> str:
    """
    Pass 2: Enhances the RoFormer vocal stem using DeepFilterNet3.
    DeepFilterNet GRU state warms up on the 3s pre-roll reflection pad.
    """
    logger.info("[PASS 2] Applying 80Hz High-Pass Filter...")
    hpf_path = pass1_vocal_path + ".hpf.wav"
    apply_highpass_filter(pass1_vocal_path, hpf_path, cutoff_hz=80)
    
    logger.info("[PASS 2] Initializing DeepFilterNet3...")
    model, df_state, _ = init_df()
    
    logger.info(f"[PASS 2] Loading Padded HPF Audio into DeepFilterNet3 (Native SR: {df_state.sr()} Hz)...")
    audio, _ = load_audio(hpf_path, sr=df_state.sr())
    
    logger.info("[PASS 2] Executing Deep Filtering (Warming up GRU on 3s reflection pad)...")
    enhanced_audio = enhance(model, df_state, audio)
    
    logger.info(f"[PASS 2] Saving Padded Vocal Track to {final_vocal_path}...")
    save_audio(final_vocal_path, enhanced_audio, df_state.sr())
    
    if os.path.exists(hpf_path):
        try: os.remove(hpf_path)
        except Exception: pass
        
    logger.info(f"[PASS 2 COMPLETE] Padded vocals saved to: {final_vocal_path}")
    return final_vocal_path


def execute_roformer_separation(
    input_audio_path: str,
    output_dir: str,
    model_file_dir: str = None,
    roformer_model: str = "model_bs_roformer_ep_317_sdr_12.9755.ckpt",
) -> dict:
    """
    Executes BS-RoFormer separation on padded audio. Returns PADDED vocal & background stems.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    if not model_file_dir:
        model_file_dir = os.getenv("MODEL_FILE_DIR", "/mnt/models/audio-separator")
    if not Path(model_file_dir).exists():
        fallback_cache = Path(tempfile.gettempdir()) / "audio-separator-models"
        fallback_cache.mkdir(parents=True, exist_ok=True)
        model_file_dir = str(fallback_cache)
        
    Path(model_file_dir).mkdir(parents=True, exist_ok=True)
    use_gpu = torch.cuda.is_available()

    if use_gpu:
        torch.cuda.empty_cache()
        gc.collect()

    logger.info(f"[ISOLATION PASS 1] Executing BS-RoFormer ({roformer_model}) on padded audio - GPU: {use_gpu}")

    def _run_sep(gpu_flag: bool):
        separator = Separator(
            output_dir=output_dir,
            output_format="WAV",
            sample_rate=44100,
            model_file_dir=model_file_dir,
            chunk_duration=600,
            use_soundfile=True,
            use_autocast=gpu_flag,
            mdxc_params={
                'overlap': 4,
                'batch_size': 1
            }
        )
        separator.load_model(model_filename=roformer_model)

        output_names = {
            "Vocals": "temp_padded_voc_pass1",
            "Instrumental": "temp_padded_bg_pass1",
        }

        return separator.separate(input_audio_path, output_names)

    try:
        output_files = _run_sep(use_gpu)
    except Exception as e:
        if use_gpu and ("out of memory" in str(e).lower() or "cuda" in str(e).lower()):
            logger.warning(f"[ISOLATION PASS 1] CUDA OOM encountered ({e}). Retrying BS-RoFormer on CPU...")
            torch.cuda.empty_cache()
            gc.collect()
            output_files = _run_sep(False)
        else:
            raise

    target_out_dir = Path(output_dir).resolve()
    padded_vocal_path = None
    padded_inst_path = None

    for path in output_files:
        p = Path(path)
        if not p.is_absolute():
            p = target_out_dir / p
        p = p.resolve()
        if not p.exists():
            cands = list(target_out_dir.glob("*temp_padded_voc_pass1*")) if "voc" in p.name else list(target_out_dir.glob("*temp_padded_bg_pass1*"))
            if cands: p = cands[0].resolve()

        if "voc" in p.name.lower():
            padded_vocal_path = str(p)
        elif "bg" in p.name.lower() or "inst" in p.name.lower():
            padded_inst_path = str(p)

    if not padded_vocal_path or not padded_inst_path:
        raise RuntimeError(f"[ISOLATION PASS 1 ERROR] Failed to map Pass 1 padded output stems: {output_files}")

    return {
        "vocals": padded_vocal_path,
        "instrumental": padded_inst_path
    }


def execute_pass1_roformer_pipeline(
    input_video_audio: str,
    output_dir: str,
    pad_ms: int = 3000
) -> dict:
    """
    Stage 1: Resamples to 44.1kHz 32-bit float, adds 3s reflection padding,
    runs BS-RoFormer (Pass 1 ONLY), and trims 3s pads to return pristine 
    unfiltered Pass 1 vocals (containing Quran + host) and instrumental track.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    padded_input_wav = os.path.join(output_dir, "_temp_padded_input.wav")
    _resample_and_pad_audio(input_video_audio, padded_input_wav, pad_ms=pad_ms)
    
    pass1_outputs = execute_roformer_separation(
        input_audio_path=padded_input_wav,
        output_dir=output_dir
    )
    padded_vocal_pass1 = pass1_outputs["vocals"]          # Contains 3s pad
    padded_bg_stem = pass1_outputs["instrumental"]        # Contains 3s pad
    
    pass1_vocal_trimmed = os.path.join(output_dir, "pass1_vocal_raw.wav")
    pass1_bg_trimmed = os.path.join(output_dir, "Audio_3_Noise_Only.wav")
    
    _trim_audio_pads_to_file(padded_vocal_pass1, pass1_vocal_trimmed, pad_ms=pad_ms)
    _trim_audio_pads_to_file(padded_bg_stem, pass1_bg_trimmed, pad_ms=pad_ms)
    
    logger.info(
        f"[PASS 1 ROFORMER COMPLETE]\n"
        f"  Pristine Unfiltered Vocals (Quran + Host) : {pass1_vocal_trimmed}\n"
        f"  Instrumental Track                       : {pass1_bg_trimmed}"
    )
    
    return {
        "pass1_vocals": pass1_vocal_trimmed,
        "instrumental": pass1_bg_trimmed,
        "padded_vocal_pass1": padded_vocal_pass1,
        "padded_input_wav": padded_input_wav,
        "padded_bg_stem": padded_bg_stem
    }


def execute_pass2_deepfilternet_pipeline(
    pass1_vocal_path: str,
    output_dir: str,
    pad_ms: int = 3000
) -> str:
    """
    Stage 4: Runs 80Hz High-Pass Filter + DeepFilterNet3 on pass1_vocal_path.
    Enhances host speech for TTS/translation while preserving 3s reflection pad warmup.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    if not pass1_vocal_path.endswith("pass1.wav"):
        padded_vocal_in = os.path.join(output_dir, "_temp_padded_pass2_in.wav")
        _resample_and_pad_audio(pass1_vocal_path, padded_vocal_in, pad_ms=pad_ms)
    else:
        padded_vocal_in = pass1_vocal_path

    padded_vocal_pass2 = os.path.join(output_dir, "_temp_padded_voc_pass2.wav")
    execute_speech_enhancement(
        pass1_vocal_path=padded_vocal_in,
        final_vocal_path=padded_vocal_pass2
    )
    
    final_dfnet_vocal_path = os.path.join(output_dir, "voc_wav.wav")
    _trim_audio_pads_to_file(padded_vocal_pass2, final_dfnet_vocal_path, pad_ms=pad_ms)
    
    # Cleanup temporary padded files
    for temp_file in [padded_vocal_in, padded_vocal_pass2]:
        if os.path.exists(temp_file) and temp_file != pass1_vocal_path:
            try: os.remove(temp_file)
            except Exception: pass

    logger.info(f"[PASS 2 DEEPFILTERNET COMPLETE] Enhanced Host Vocals saved to: {final_dfnet_vocal_path}")
    return final_dfnet_vocal_path


def execute_full_isolation_pipeline(
    input_video_audio: str,
    output_dir: str,
    pad_ms: int = 3000
) -> dict:
    """
    Legacy wrapper executing Pass 1 and Pass 2 sequentially.
    Note: Pass 1 Branching topology in orchestrator calls Pass 1 and Pass 2 independently.
    """
    pass1_res = execute_pass1_roformer_pipeline(input_video_audio, output_dir, pad_ms=pad_ms)
    dfnet_vocals = execute_pass2_deepfilternet_pipeline(pass1_res["pass1_vocals"], output_dir, pad_ms=pad_ms)
    return {
        "vocals": dfnet_vocals,
        "pass1_vocals": pass1_res["pass1_vocals"],
        "instrumental": pass1_res["instrumental"]
    }


def run_vcta_pipeline(input_path: str, output_dir: str, device: str = None, preserve_quran_verses: bool = True) -> dict:
    """
    Orchestrated VCTA pipeline v3.3:
      1. BS-RoFormer (Pass 1) — separates audio into raw vocals (pass1_vocal_raw) + background (pass1_bg)
      2. Enrollment Clip Generation — extracts host_enrollment_ref.wav via Silero VAD anchor
      3. Neural Target Speaker Extraction (TSE) — extracts pristine_host_vocals.wav using host_enrollment_ref
      4. Quran Verses Preservation — restores Quran recitation into background stem (restored_background_stem.wav)
      5. DeepFilterNet (Pass 2) — enhances pristine host voice for AI translation & dubbing
    """
    out = Path(output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)

    tmp_dir = out / "_vcta_temp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    # ── Stage 1: Pass 1 RoFormer ────────────────────────────────────────────────
    logger.info("[VCTA v3.3] Stage 1: BS-RoFormer Pass 1 separation...")
    pass1_res = execute_pass1_roformer_pipeline(
        input_video_audio=input_path,
        output_dir=str(tmp_dir),
        pad_ms=3000
    )
    pass1_vocal_raw = pass1_res["pass1_vocals"]   # pristine: host + Quran + singing
    pass1_bg = pass1_res["instrumental"]           # game sounds / music only

    # ── Stage 2: Target Speaker Acoustic Routing & Quran Restoration ──────────
    pristine_host_path = str(tmp_dir / "pristine_host_vocals.wav")
    purged_secondary_path = str(tmp_dir / "purged_secondary_audio.wav")
    restored_bg_path = str(out / "Audio_3_Noise_Only.wav")

    logger.info(f"[VCTA v9.3] Stage 2: Acoustic Routing (Preserve Quran: {preserve_quran_verses})...")
    try:
        from app.services.vcta.tse import (
            process_vcta_acoustic_routing_and_restoration,
            mix_secondary_into_background
        )
        if preserve_quran_verses:
            process_vcta_acoustic_routing_and_restoration(
                voc_wav_path=pass1_vocal_raw,
                pristine_host_output_path=pristine_host_path,
                purged_secondary_output_path=purged_secondary_path
            )
            # Mix secondary Quran verses blindly into the background stem
            mix_secondary_into_background(
                instrumental_path=pass1_bg,
                purged_secondary_path=purged_secondary_path,
                output_restored_bg_path=restored_bg_path
            )
        else:
            pristine_host_path = pass1_vocal_raw
            shutil.copy2(pass1_bg, restored_bg_path)
    except Exception as tse_err:
        logger.warning(f"[VCTA v9.3] Vocal isolation warning: {tse_err}")
        pristine_host_path = pass1_vocal_raw
        shutil.copy2(pass1_bg, restored_bg_path)

    # ── Stage 4: DeepFilterNet Pass 2 on pristine host vocals ONLY ──────────────
    logger.info("[VCTA v2.7] Stage 4: DeepFilterNet Pass 2 speech enhancement on host voice...")
    dfnet_vocal_path = execute_pass2_deepfilternet_pipeline(
        pass1_vocal_path=pristine_host_path,
        output_dir=str(tmp_dir),
        pad_ms=3000
    )

    # ── Stage 5: Export final stems ─────────────────────────────────────────────
    logger.info("[VCTA v2.7] Stage 5: Exporting final stems...")

    # Load DeepFilterNet output (48 kHz) for downstream consumers
    vocal_clean, vocal_sr = librosa.load(dfnet_vocal_path, sr=None, mono=False)
    vocal_clean = vocal_clean if vocal_clean.ndim == 2 else np.stack([vocal_clean, vocal_clean])

    # Apply original silence mask to wipe any residual noise in silent gaps
    audio_orig, sr_orig = load_and_validate(input_path)
    silence_mask = generate_silence_mask(audio_orig, sr_orig)
    del audio_orig  # free RAM immediately

    silence_mask_resampled = librosa.resample(
        silence_mask.astype(float), orig_sr=sr_orig, target_sr=vocal_sr
    ) > 0.5
    min_len = min(vocal_clean.shape[1], len(silence_mask_resampled))
    vocal_clean = restore_silence_regions(
        vocal_clean[:, :min_len], silence_mask_resampled[:min_len]
    )

    # 16 kHz mono for Pyannote (used only in chunker for translation gating)
    mono_16k = librosa.resample(vocal_clean.mean(axis=0), orig_sr=vocal_sr, target_sr=16000)
    mono_16k = true_peak_normalize(mono_16k[np.newaxis], sr=16000, target_dbtp=-3.0)
    pyannote_path = out / "vocals_stem_pyannote_16k.wav"
    sf.write(str(pyannote_path), mono_16k[0], 16000, subtype='PCM_16')

    # Fish Audio target: -1 dBTP, 44.1 kHz stereo
    fish = true_peak_normalize(vocal_clean, sr=vocal_sr, target_dbtp=-1.0)
    fish_path = out / "vocals_stem_fish_44k1.wav"
    sf.write(str(fish_path), fish.T, vocal_sr, subtype='FLOAT')

    # Cleanup temp dir
    shutil.rmtree(tmp_dir, ignore_errors=True)

    return {
        'paths': {
            'pyannote': str(pyannote_path),
            'fish_audio': str(fish_path),
            'instrumental': restored_bg_path,
            'vocals': str(fish_path)
        },
        'metrics': {'pass': True},
        'phase_offset_samples': 0
    }
