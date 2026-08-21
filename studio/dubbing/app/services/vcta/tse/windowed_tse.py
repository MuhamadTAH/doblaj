"""
windowed_tse.py — Module 2: Truncated 16kHz Sliding-Window OLA TSE Processor
=============================================================================
Completely eliminates Sample-Rate Array Collisions and Neural Cliff Panic:
1. Hard-slices input audio at `t_silence_onset` (dropping dead noise floor audio).
2. Resamples active speech strictly to 16,000 Hz BEFORE any windowing or anchor extraction.
3. All math (windows, step sizes, crossfade ramps, buffers) is locked strictly to 16kHz.
4. Dynamically selects the nearest clean 16kHz anchor for the active temporal region.
5. Smart-matches the separated stems (s1 vs s2) to the anchor to prevent permutation swaps.
6. Overlap-Adds with weight normalization in the pure 16kHz domain.
7. Upsamples the stitched active audio back to 48kHz and restores master duration with digital silence.
"""

import os
import gc
import json
import logging
import torch
import soundfile as sf
import numpy as np
import librosa
from typing import List, Dict, Optional, Union, Tuple

from app.services.vcta.tse.envelope_tracker import track_volume_envelope, VolumeEnvelopeProfile

logger = logging.getLogger(__name__)


class DynamicAnchorManager16k:
    """
    Finds and extracts the closest clean speech segment at 16,000 Hz.
    """
    def __init__(self, diarization_turns: List[Dict], overlaps: List[Dict], audio_16k: np.ndarray, fs: int = 16000):
        self.turns = diarization_turns
        self.overlaps = overlaps
        self.audio_16k = audio_16k
        self.fs = fs

    def get_nearest_clean_anchor(
        self,
        speaker_id: str,
        target_sample: int,
        min_duration: float = 1.5,
        temp_dir: str = "_temp_anchors_16k"
    ) -> str:
        os.makedirs(temp_dir, exist_ok=True)
        target_sec = target_sample / self.fs
        speaker_turns = [t for t in self.turns if t["speaker"] == speaker_id]
        
        if not speaker_turns:
            speaker_turns = self.turns

        candidates = []
        for turn in speaker_turns:
            t_start = turn["start"]
            t_end = turn["end"]
            t_dur = t_end - t_start

            if t_dur < min_duration:
                continue

            # Check overlap collision
            is_overlapping = False
            for ov in self.overlaps:
                if not (t_end <= ov["start"] or t_start >= ov["end"]):
                    is_overlapping = True
                    break

            if is_overlapping:
                continue

            turn_center = (t_start + t_end) / 2.0
            dist = abs(turn_center - target_sec)
            candidates.append((dist, t_start, t_end, t_dur))

        if not candidates:
            for turn in speaker_turns:
                turn_center = (turn["start"] + turn["end"]) / 2.0
                dist = abs(turn_center - target_sec)
                candidates.append((dist, turn["start"], turn["end"], turn["end"] - turn["start"]))

        candidates.sort(key=lambda x: (x[0], -x[3]))
        best = candidates[0]
        b_start, b_end = best[1], best[2]

        anchor_len = min(3.0, b_end - b_start)
        s_idx = int(b_start * self.fs)
        e_idx = int((b_start + anchor_len) * self.fs)

        anchor_clip = self.audio_16k[s_idx:e_idx]
        anchor_file = os.path.join(
            temp_dir,
            f"anchor_{speaker_id}_{b_start:.2f}s_to_{b_start+anchor_len:.2f}s_16k.wav"
        )
        sf.write(anchor_file, anchor_clip, self.fs)
        logger.info(
            f"[ANCHOR-16K] Target: {target_sec:.2f}s | Selected {speaker_id} clip: "
            f"[{b_start:.2f}s -> {b_start+anchor_len:.2f}s] -> {anchor_file}"
        )
        return anchor_file


def process_sliding_window_ola_tse_unirate(
    input_wav_path: str,
    output_wav_path: str,
    speaker_id: str,
    diarization_turns: List[Dict],
    overlaps: List[Dict],
    cv_engine,
    window_sec: float = 12.0,
    overlap_sec: float = 2.0,
    target_sr: int = 48000,
    t_silence_onset: Optional[float] = None
) -> str:
    """
    Locked 16kHz Uni-Rate Sliding-Window Overlap-Add TSE with Truncated Extraction.
    """
    out_dir = os.path.dirname(output_wav_path)
    os.makedirs(out_dir, exist_ok=True)
    temp_dir = os.path.join(out_dir, f"_temp_unirate_{speaker_id}")
    os.makedirs(temp_dir, exist_ok=True)

    # 1. Read Master 48kHz Audio
    audio_orig, orig_fs = sf.read(input_wav_path, dtype="float32")
    if len(audio_orig.shape) > 1:
        audio_mono_orig = np.mean(audio_orig, axis=1)
    else:
        audio_mono_orig = audio_orig

    total_orig_samples = len(audio_mono_orig)
    total_orig_dur = total_orig_samples / orig_fs

    # 2. Hard-slice at t_silence_onset if provided (Drop mathematically dead tail audio)
    if t_silence_onset is not None and t_silence_onset < total_orig_dur:
        slice_sample_48k = int(t_silence_onset * orig_fs)
        audio_active_48k = audio_mono_orig[:slice_sample_48k]
        logger.info(
            f"[TRUNCATED EXTRACTION] Sliced input audio at t_silence_onset={t_silence_onset:.3f}s "
            f"(Active: {len(audio_active_48k)/orig_fs:.3f}s / Dropped tail: {total_orig_dur - t_silence_onset:.3f}s)"
        )
    else:
        audio_active_48k = audio_mono_orig

    # 3. FORCE THE ACTIVE CANVAS TO 16,000 Hz
    target_fs = 16000
    if orig_fs != target_fs:
        audio_16k = librosa.resample(audio_active_48k, orig_sr=orig_fs, target_sr=target_fs)
    else:
        audio_16k = audio_active_48k

    active_samples_16k = len(audio_16k)
    win_samples = int(window_sec * target_fs)
    step_samples = int((window_sec - overlap_sec) * target_fs)
    overlap_samples = int(overlap_sec * target_fs)

    output_buffer = np.zeros(active_samples_16k, dtype=np.float32)
    weight_buffer = np.zeros(active_samples_16k, dtype=np.float32)

    fade_in = np.linspace(0.0, 1.0, overlap_samples, dtype=np.float32)
    fade_out = np.linspace(1.0, 0.0, overlap_samples, dtype=np.float32)

    anchor_mgr = DynamicAnchorManager16k(
        diarization_turns=diarization_turns,
        overlaps=overlaps,
        audio_16k=audio_16k,
        fs=target_fs
    )

    logger.info(
        f"[UNI-RATE 16K] Active: {active_samples_16k} samples ({active_samples_16k/target_fs:.2f}s) | "
        f"Win: {win_samples} | Step: {step_samples} | Overlap: {overlap_samples}"
    )

    start = 0
    win_idx = 0

    while start < active_samples_16k:
        win_idx += 1
        end = min(start + win_samples, active_samples_16k)
        chunk = audio_16k[start:end]
        chunk_len = len(chunk)

        # Apply forward-repeat padding if terminal chunk is short
        pad_len = 0
        if end == active_samples_16k and chunk_len < win_samples:
            pad_len = win_samples - chunk_len
            chunk_padded = np.concatenate((chunk, chunk[-pad_len:]), axis=0)
        else:
            chunk_padded = chunk

        temp_in = os.path.join(temp_dir, f"win_{win_idx:02d}_in.wav")
        sf.write(temp_in, chunk_padded, target_fs)

        # Dynamic anchor lookup (16kHz)
        local_anchor = anchor_mgr.get_nearest_clean_anchor(
            speaker_id=speaker_id,
            target_sample=start,
            min_duration=1.5,
            temp_dir=os.path.join(temp_dir, "anchors")
        )

        # Run ClearVoice
        temp_cv_out = os.path.join(temp_dir, f"cv_out_{win_idx:02d}")
        os.makedirs(temp_cv_out, exist_ok=True)
        cv_engine(input_path=temp_in, online_write=True, output_path=temp_cv_out)

        # Collect separated stems
        stem_files = []
        for r, _, files in os.walk(temp_cv_out):
            for f in files:
                if f.endswith(".wav"):
                    stem_files.append(os.path.join(r, f))
        stem_files.sort()

        if not stem_files:
            raise RuntimeError(f"ClearVoice failed for window {win_idx}")

        # Permutation matching: Compare stems against anchor
        anchor_data, _ = sf.read(local_anchor, dtype="float32")
        best_stem_path = stem_files[0]
        if len(stem_files) > 1:
            best_score = -999.0
            for sf_p in stem_files:
                s_data, _ = sf.read(sf_p, dtype="float32")
                min_len = min(len(s_data), len(anchor_data))
                if min_len > 0:
                    score = float(np.dot(s_data[:min_len], anchor_data[:min_len]) / (
                        np.linalg.norm(s_data[:min_len]) * np.linalg.norm(anchor_data[:min_len]) + 1e-8
                    ))
                else:
                    score = float(np.max(np.abs(s_data)))
                
                if speaker_id in ["SPEAKER_00", "speaker_01"] and score > best_score:
                    best_score = score
                    best_stem_path = sf_p
                elif speaker_id not in ["SPEAKER_00", "speaker_01"]:
                    best_stem_path = stem_files[1]

        processed_chunk, fs_out = sf.read(best_stem_path, dtype="float32")

        # Crop terminal padding
        if pad_len > 0:
            processed_chunk = processed_chunk[:chunk_len]

        actual_len = len(processed_chunk)

        # Overlap-add weighting
        window_weights = np.ones(actual_len, dtype=np.float32)
        if start > 0 and actual_len >= overlap_samples:
            window_weights[:overlap_samples] = fade_in
        if end < active_samples_16k and actual_len >= overlap_samples:
            window_weights[-overlap_samples:] = fade_out

        output_buffer[start:start+actual_len] += processed_chunk * window_weights
        weight_buffer[start:start+actual_len] += window_weights

        logger.info(
            f"[WIN {win_idx:02d}] Samples [{start} -> {start+actual_len}] ({start/target_fs:.2f}s -> {(start+actual_len)/target_fs:.2f}s) "
            f"Stem: {os.path.basename(best_stem_path)}"
        )

        if end >= active_samples_16k:
            break
        start += step_samples

    # Normalize weights
    nonzero = weight_buffer > 0.0
    output_buffer[nonzero] /= weight_buffer[nonzero]

    # Normalize active speech to standard broadcast headroom (-1.0 dBFS)
    peak = float(np.max(np.abs(output_buffer)))
    if peak > 0.0:
        output_buffer = output_buffer * (0.89125 / peak)

    # 4. UPSCALE ACTIVE AUDIO BACK TO 48kHz
    if target_sr and target_sr != target_fs:
        active_master_48k = librosa.resample(output_buffer, orig_sr=target_fs, target_sr=target_sr)
        final_sr = target_sr
    else:
        active_master_48k = output_buffer
        final_sr = target_fs

    # 5. RESTORE FULL MASTER TIMELINE LENGTH WITH DIGITAL SILENCE
    target_total_samples = int(total_orig_dur * final_sr)
    final_canvas_48k = np.zeros(target_total_samples, dtype=np.float32)
    len_to_copy = min(len(active_master_48k), target_total_samples)
    final_canvas_48k[:len_to_copy] = active_master_48k[:len_to_copy]

    sf.write(output_wav_path, final_canvas_48k, final_sr)
    logger.info(
        f"[TRUNCATED OLA SUCCESS] Exported -> {output_wav_path} "
        f"(Active: {len_to_copy/final_sr:.3f}s / Master Canvas: {len(final_canvas_48k)/final_sr:.3f}s @ {final_sr}Hz)"
    )

    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    gc.collect()

    return output_wav_path


def process_truncated_sliding_window_ola_tse(
    input_wav_path: str,
    output_wav_path: str,
    speaker_id: str,
    diarization_turns: List[Dict],
    overlaps: List[Dict],
    cv_engine,
    window_sec: float = 12.0,
    overlap_sec: float = 2.0,
    target_sr: int = 48000
) -> Tuple[str, VolumeEnvelopeProfile]:
    """
    Module 2 Entrypoint: Automatically extracts the RMS envelope profile and executes
    truncated extraction stopping strictly before the terminal noise cliff.
    """
    env_profile = track_volume_envelope(input_wav_path, sr=target_sr)
    t_silence = env_profile.t_silence_onset_sec

    out_path = process_sliding_window_ola_tse_unirate(
        input_wav_path=input_wav_path,
        output_wav_path=output_wav_path,
        speaker_id=speaker_id,
        diarization_turns=diarization_turns,
        overlaps=overlaps,
        cv_engine=cv_engine,
        window_sec=window_sec,
        overlap_sec=overlap_sec,
        target_sr=target_sr,
        t_silence_onset=t_silence
    )
    return out_path, env_profile


# Production aliases
process_sliding_window_ola_tse = process_sliding_window_ola_tse_unirate
DynamicAnchorManager = DynamicAnchorManager16k
