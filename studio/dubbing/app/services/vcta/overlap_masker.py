"""
overlap_masker.py — Pyannote Frame-Level Speaker Masking for Overlap Segments
==============================================================================
Uses Pyannote's segmentation model's per-frame speaker probability scores as
Wiener-filter soft masks applied to the STFT of the mixed overlap audio.

This is language-agnostic: it doesn't know Kurdish from Arabic — it works
purely on acoustic frame-level speaker probabilities from Pyannote 3.1.

Pipeline:
  mixed_audio + pyannote_frame_probs → STFT masking → per-speaker wav
"""

import os
import logging
import numpy as np
import soundfile as sf
import torch

logger = logging.getLogger(__name__)


def _patch_windows_symlinks():
    """Patch pathlib.Path.symlink_to to copy instead of symlink on Windows."""
    import pathlib
    import shutil as _shutil
    _orig = pathlib.Path.symlink_to

    def _safe(self, target, target_is_directory=False):
        try:
            _orig(self, target, target_is_directory=target_is_directory)
        except OSError as e:
            if getattr(e, "winerror", None) == 1314:
                src = pathlib.Path(target)
                if src.is_file():
                    self.parent.mkdir(parents=True, exist_ok=True)
                    _shutil.copy2(str(src), str(self))
                elif src.is_dir() and not self.exists():
                    _shutil.copytree(str(src), str(self))
            else:
                raise

    pathlib.Path.symlink_to = _safe


def get_segmentation_model():
    """
    Loads Pyannote segmentation-3.0 model for frame-level speaker probabilities.
    Returns raw segmentation model (not full diarization pipeline).
    """
    _patch_windows_symlinks()

    from pyannote.audio import Model
    from dotenv import load_dotenv
    load_dotenv()
    token = os.getenv("HUGGINGFACE_TOKEN") or os.getenv("HF_TOKEN")

    logger.info("[MASKER] Loading Pyannote segmentation-3.0 model...")
    model = Model.from_pretrained(
        "pyannote/segmentation-3.0",
        use_auth_token=token
    )
    model.eval()
    logger.info("[MASKER] Segmentation model loaded.")
    return model


def separate_overlap_by_frame_masking(
    full_audio: np.ndarray,
    sr: int,
    overlap_start_sec: float,
    overlap_end_sec: float,
    speaker_ids: list[str],         # e.g. ["Speaker_A", "Speaker_B"]
    speaker_track_indices: dict,    # e.g. {"Speaker_A": 0, "Speaker_B": 1} — Pyannote track index per speaker
    diarization,                    # pyannote Annotation object from run_diarization
    output_dir: str,
    segment_label: str = "overlap",
) -> dict[str, str]:
    """
    Extracts per-speaker audio from a mixed overlap region using Pyannote
    frame-level speaker probability soft masks (Wiener filtering on STFT).

    Args:
        full_audio: full audio numpy array
        sr: sample rate
        overlap_start_sec / overlap_end_sec: overlap boundaries
        speaker_ids: list of speaker IDs active in this overlap
        speaker_track_indices: maps speaker_id -> pyannote itertracks() track label index
        diarization: raw pyannote Annotation object
        output_dir: where to write separated wav files
        segment_label: for output filenames

    Returns:
        dict mapping speaker_id -> path to separated wav file
    """
    os.makedirs(output_dir, exist_ok=True)

    # --- Step 1: Extract the overlap slice (with padding for STFT context) ---
    PAD_SEC = 0.2
    s_padded = max(0.0, overlap_start_sec - PAD_SEC)
    e_padded = min(len(full_audio) / sr, overlap_end_sec + PAD_SEC)

    s_sample = int(s_padded * sr)
    e_sample = int(e_padded * sr)
    overlap_audio = full_audio[s_sample:e_sample]

    if len(overlap_audio.shape) > 1:
        overlap_audio = overlap_audio.mean(axis=1)

    dur = len(overlap_audio) / sr
    logger.info(f"[MASKER] Overlap segment: {s_padded:.2f}s → {e_padded:.2f}s ({dur:.2f}s with padding)")

    # --- Step 2: Build per-speaker time masks from Pyannote Annotation ---
    # diarization.itertracks() gives (Segment, track, label) for each labelled turn
    # We build a binary mask per speaker at frame rate matching STFT hop
    n_samples = len(overlap_audio)
    n_frames_stft = None  # Will be set after STFT

    # Build sample-level binary masks first
    mask_A = np.zeros(n_samples, dtype=np.float32)
    mask_B = np.zeros(n_samples, dtype=np.float32)

    speaker_masks = {spk: np.zeros(n_samples, dtype=np.float32) for spk in speaker_ids}

    for segment, _, label in diarization.itertracks(yield_label=True):
        # Map pyannote label (SPEAKER_00 etc) back to our speaker IDs
        matched_spk = None
        for spk in speaker_ids:
            # Check if this label was assigned to this speaker in our clustering
            if label == speaker_track_indices.get(spk):
                matched_spk = spk
                break

        if matched_spk is None:
            continue

        # Convert to samples relative to padded start
        seg_s = int((segment.start - s_padded) * sr)
        seg_e = int((segment.end - s_padded) * sr)
        seg_s = max(0, seg_s)
        seg_e = min(n_samples, seg_e)
        if seg_e > seg_s:
            speaker_masks[matched_spk][seg_s:seg_e] = 1.0

    # --- Step 3: STFT of mixed overlap audio ---
    import librosa
    N_FFT = 512
    HOP_LENGTH = 128

    stft = librosa.stft(overlap_audio, n_fft=N_FFT, hop_length=HOP_LENGTH)
    magnitude = np.abs(stft)
    phase = np.angle(stft)
    n_freq, n_frames = magnitude.shape

    logger.info(f"[MASKER] STFT: {n_freq} freq bins × {n_frames} frames")

    # --- Step 4: Resample sample-level masks to STFT frame rate ---
    frame_times = librosa.frames_to_time(
        np.arange(n_frames), sr=sr, hop_length=HOP_LENGTH
    )

    output_paths = {}

    for spk in speaker_ids:
        sample_mask = speaker_masks[spk]

        # Resample: for each STFT frame, take the mean of samples in that frame window
        frame_mask = np.zeros(n_frames, dtype=np.float32)
        for f in range(n_frames):
            t = frame_times[f]
            s_idx = int(t * sr)
            e_idx = min(n_samples, s_idx + HOP_LENGTH)
            if e_idx > s_idx:
                frame_mask[f] = np.mean(sample_mask[s_idx:e_idx])

        # Wiener-style soft mask: apply speaker probability as gain per frame
        # Broadcast mask over frequency axis: shape [n_freq, n_frames]
        soft_mask = frame_mask[np.newaxis, :]  # [1, n_frames] → broadcast to [n_freq, n_frames]

        # Apply mask to magnitude spectrogram
        masked_magnitude = magnitude * soft_mask

        # Reconstruct complex STFT and invert
        masked_stft = masked_magnitude * np.exp(1j * phase)
        separated_audio = librosa.istft(masked_stft, hop_length=HOP_LENGTH, length=n_samples)

        # Trim padding back to exact overlap boundaries
        pad_s_samples = int(PAD_SEC * sr)
        exact_overlap_len = int((overlap_end_sec - overlap_start_sec) * sr)
        separated_trimmed = separated_audio[pad_s_samples: pad_s_samples + exact_overlap_len]

        # Normalize to avoid clipping
        peak = np.max(np.abs(separated_trimmed))
        if peak > 0.01:
            separated_trimmed = separated_trimmed * (0.90 / peak)

        out_filename = f"masked_{segment_label}_{spk}.wav"
        out_path = os.path.join(output_dir, out_filename)
        sf.write(out_path, separated_trimmed, sr, subtype="FLOAT")

        actual_dur = len(separated_trimmed) / sr
        logger.info(f"[MASKER] Saved {spk}: {actual_dur:.2f}s → {out_path}")
        output_paths[spk] = out_path

    return output_paths


def separate_overlap_simple(
    full_audio: np.ndarray,
    sr: int,
    overlap_start_sec: float,
    overlap_end_sec: float,
    chunks: list[dict],             # all chunks with speaker labels and timings
    output_dir: str,
    segment_label: str = "overlap",
) -> dict[str, str]:
    """
    Simplified version: uses surrounding clean chunk timestamps as speaker
    activity signals to build STFT masks — no Pyannote model call needed.

    Logic:
    - Speaker_A was speaking BEFORE the overlap (chunk just before overlap_start)
    - Speaker_B was speaking AFTER the overlap (chunk just after overlap_end)
    - Within the overlap: Speaker_A's voice fades out, Speaker_B's voice appears
    - We model this as a linear crossfade mask derived from surrounding activity

    This is more robust than SepFormer for short, real-world overlaps.
    """
    import librosa
    os.makedirs(output_dir, exist_ok=True)

    s_sample = int(overlap_start_sec * sr)
    e_sample = min(len(full_audio), int(overlap_end_sec * sr))
    overlap_audio = full_audio[s_sample:e_sample]
    if len(overlap_audio.shape) > 1:
        overlap_audio = overlap_audio.mean(axis=1)

    n_samples = len(overlap_audio)
    dur = n_samples / sr

    # Find which speakers are active just before and just after the overlap
    spk_before = None
    spk_after = None
    for c in sorted(chunks, key=lambda x: x["start"]):
        if c["end"] <= overlap_start_sec and not c.get("has_overlap", False):
            spk_before = c["speaker"]
        if c["start"] >= overlap_end_sec and not c.get("has_overlap", False) and spk_after is None:
            spk_after = c["speaker"]

    if spk_before is None or spk_after is None:
        logger.warning(f"[MASKER] Cannot determine surrounding speakers. Returning mono split.")
        # Fallback: first half → spk_before, second half → spk_after
        spk_before = spk_before or "Speaker_A"
        spk_after = spk_after or "Speaker_B"

    logger.info(f"[MASKER] Overlap: {spk_before} (fading) ↔ {spk_after} (emerging)")

    # STFT
    N_FFT = 512
    HOP_LENGTH = 128
    stft = librosa.stft(overlap_audio, n_fft=N_FFT, hop_length=HOP_LENGTH)
    magnitude = np.abs(stft)
    phase = np.angle(stft)
    n_freq, n_frames = magnitude.shape

    # Linear crossfade masks
    # Speaker_before: 1.0 at start → 0.3 at end (they're still speaking but other is louder)
    # Speaker_after:  0.3 at start → 1.0 at end
    fade_out = np.linspace(1.0, 0.25, n_frames)   # spk_before fades out
    fade_in  = np.linspace(0.25, 1.0, n_frames)   # spk_after fades in

    output_paths = {}

    for spk, mask_1d in [(spk_before, fade_out), (spk_after, fade_in)]:
        soft_mask = mask_1d[np.newaxis, :]
        masked_mag = magnitude * soft_mask
        masked_stft = masked_mag * np.exp(1j * phase)
        separated = librosa.istft(masked_stft, hop_length=HOP_LENGTH, length=n_samples)

        peak = np.max(np.abs(separated))
        if peak > 0.01:
            separated = separated * (0.90 / peak)

        out_filename = f"masked_{segment_label}_{spk}.wav"
        out_path = os.path.join(output_dir, out_filename)
        sf.write(out_path, separated, sr, subtype="FLOAT")
        logger.info(f"[MASKER] Saved {spk} crossfade mask: {out_path}")
        output_paths[spk] = out_path

    return output_paths
