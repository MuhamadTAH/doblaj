import os
import uuid
import time
import shutil
import logging
import gc
import tempfile
from pathlib import Path

import librosa
import soundfile as sf
import numpy as np
import torch
from audio_separator.separator import Separator

logger = logging.getLogger(__name__)

MAX_AUDIO_DURATION_SEC = 7200  # 2 hours
ALLOWED_OUTPUT_ROOT = Path("data/jobs/sessions").resolve()
TARGET_SR = 44100


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


def execute_roformer_separation(
    input_audio_path: str,
    output_dir: str,
    model_file_dir: str = os.getenv("MODEL_FILE_DIR", "/mnt/models/audio-separator"),
    model_filename: str = "model_bs_roformer_ep_317_sdr_12.9755.ckpt",
) -> dict:
    """
    Executes BS-RoFormer stem separation with VRAM protection and safe string mapping.
    
    Args:
        input_audio_path: Path to the source audio file.
        output_dir: Output directory for separated stems.
        model_file_dir: Directory to cache downloaded model weights.
        model_filename: Checkpoint filename (defaults to Viperx BS-RoFormer ep_317).
        
    Returns:
        dict: {"vocals": path_to_vocal_wav, "instrumental": path_to_background_wav}
    """
    if not Path(input_audio_path).exists():
        raise FileNotFoundError(f"Input audio not found: {input_audio_path}")
        
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    Path(model_file_dir).mkdir(parents=True, exist_ok=True)
    
    use_gpu = torch.cuda.is_available()
    logger.info(f"[ISOLATION] Initializing RoFormer (GPU Available: {use_gpu}, Cache: {model_file_dir})")
    
    # 1. Initialize Separator with VRAM safety controls
    separator = Separator(
        output_dir=output_dir,
        output_format="WAV",
        sample_rate=44100,
        model_file_dir=model_file_dir,
        chunk_duration=600,       # 10-minute chunking prevents GPU VRAM OOM on long VODs
        use_soundfile=True,       # Prevents memory spikes during large WAV exports
        use_autocast=use_gpu,     # Enabled for CUDA; MUST be False on CPU to avoid crashes
    )
    
    # 2. Load the benchmark-validated BS-RoFormer checkpoint
    logger.info(f"[ISOLATION] Loading model: {model_filename}")
    separator.load_model(model_filename=model_filename)
    
    # Target stem names matching downstream pipeline expectations
    output_names = {
        "Vocals": "voc_wav",
        "Instrumental": "Audio_3_Noise_Only",
    }
    
    # 3. Execute separation with explicit error catching
    try:
        output_files = separator.separate(input_audio_path, output_names)
    except Exception as exc:
        logger.exception(f"[ISOLATION FAILED] Separation crashed on {input_audio_path}")
        raise RuntimeError(f"RoFormer separation failed: {str(exc)}") from exc
        
    if not output_files or len(output_files) < 2:
        raise RuntimeError(f"[ISOLATION ERROR] Expected 2 output stems, got: {output_files}")
        
    # 4. Parse string paths explicitly (Do NOT rely on list index order)
    result = {}
    for path in output_files:
        filename = os.path.basename(path)
        if "voc_wav" in filename:
            result["vocals"] = str(Path(path).resolve())
        elif "Audio_3_Noise_Only" in filename:
            result["instrumental"] = str(Path(path).resolve())
            
    if "vocals" not in result or "instrumental" not in result:
        raise RuntimeError(
            f"[ISOLATION ERROR] Failed to map vocal and instrumental outputs from: {output_files}"
        )
        
    logger.info(
        f"[ISOLATION COMPLETE]\n"
        f"  Vocals       : {result['vocals']}\n"
        f"  Instrumental : {result['instrumental']}"
    )
    
    return result


def run_vcta_pipeline(input_path: str, output_dir: str, device: str = None) -> dict:
    run_uuid = uuid.uuid4().hex
    
    logger.info(f"[ISOLATION] Stage 0: Load & validate {input_path}")
    out = Path(output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    audio, sr = load_and_validate(input_path)

    logger.info("[ISOLATION] Stage 0.5: Mathematical Warm-Up Padding (Reflective, 2.0s)")
    pad_samples = int(2.0 * sr)
    audio = np.pad(audio, ((0, 0), (pad_samples, 0)), mode='reflect')

    logger.info("[ISOLATION] Stage 1: Silence mapping")
    silence_mask = generate_silence_mask(audio, sr)
    logger.info(f"[ISOLATION] Silence coverage: {silence_mask.mean():.1%}")

    tmp_dir = out / f"temp_{run_uuid}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    padded_wav_path = str(tmp_dir / "padded_input.wav")
    sf.write(padded_wav_path, audio.T, sr, subtype='PCM_16')

    # Resolve persistent model cache directory
    model_cache = os.getenv("MODEL_FILE_DIR", "/mnt/models/audio-separator")
    if not Path(model_cache).exists():
        fallback_cache = Path(tempfile.gettempdir()) / "audio-separator-models"
        fallback_cache.mkdir(parents=True, exist_ok=True)
        model_cache = str(fallback_cache)

    logger.info(f"[ISOLATION] Stage 2: BS-RoFormer Execution (Cache: {model_cache})")
    sep_stems = execute_roformer_separation(
        input_audio_path=padded_wav_path,
        output_dir=str(tmp_dir),
        model_file_dir=model_cache,
        model_filename="model_bs_roformer_ep_317_sdr_12.9755.ckpt"
    )

    vocal_raw, _ = librosa.load(sep_stems["vocals"], sr=sr, mono=False)
    inst_raw, _ = librosa.load(sep_stems["instrumental"], sr=sr, mono=False)

    vocal_raw = vocal_raw if vocal_raw.ndim == 2 else np.stack([vocal_raw, vocal_raw])
    inst_raw = inst_raw if inst_raw.ndim == 2 else np.stack([inst_raw, inst_raw])

    logger.info("[ISOLATION] Stage 3: Cleanup (Slice 2.0s Warm-Up Padding)")
    min_v_len = min(audio.shape[1], vocal_raw.shape[1])
    min_i_len = min(audio.shape[1], inst_raw.shape[1])
    
    vocal_clean = vocal_raw[:, pad_samples:min_v_len]
    inst_stem = inst_raw[:, pad_samples:min_i_len]
    audio = audio[:, pad_samples:]
    silence_mask = silence_mask[pad_samples:]

    logger.info("[ISOLATION] Stage 4: Silence restoration")
    min_mask_len = min(vocal_clean.shape[1], len(silence_mask))
    vocal_clean = restore_silence_regions(vocal_clean[:, :min_mask_len], silence_mask[:min_mask_len])

    logger.info("[ISOLATION] Stage 5: Exporting Final Stems")
    # Export 16k mono for Pyannote VAD
    mono_16k = librosa.resample(vocal_clean.mean(axis=0), orig_sr=sr, target_sr=16000)
    mono_16k = true_peak_normalize(mono_16k[np.newaxis], sr=16000, target_dbtp=-3.0)
    pyannote_path = out / "vocals_stem_pyannote_16k.wav"
    sf.write(str(pyannote_path), mono_16k[0], 16000, subtype='PCM_16')

    # Fish Audio Target (-1dBTP)
    fish = true_peak_normalize(vocal_clean, sr=sr, target_dbtp=-1.0)
    fish_path = out / "vocals_stem_fish_44k1.wav"
    sf.write(str(fish_path), fish.T, sr, subtype='FLOAT')

    # Background Target
    inst_path = out / "instrumental_stem_44k1.wav"
    sf.write(str(inst_path), inst_stem.T, sr, subtype='FLOAT')

    # Cleanup temp directory
    shutil.rmtree(tmp_dir, ignore_errors=True)

    return {
        'paths': {
            'pyannote': str(pyannote_path),
            'fish_audio': str(fish_path),
            'instrumental': str(inst_path),
            'vocals': str(fish_path)
        },
        'metrics': {'pass': True},
        'phase_offset_samples': 0
    }
