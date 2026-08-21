"""
envelope_tracker.py — Module 1: RMS Volume Envelope Tracker & Fade-Out Detector
================================================================================
Tracks the dynamic volume envelope of 48kHz master audio:
1. Calculates rolling RMS energy using short analysis frames (50ms window, 10ms hop).
2. Estimates the acoustic noise floor and sets an adaptive noise floor margin.
3. Discovers `t_silence_onset`: The exact millisecond where signal energy dips below
   the noise floor margin and does not recover (the terminal silence/fade cliff).
4. Extracts `fade_curve_array`: The normalized amplitude multiplier curve (1.0 -> 0.0)
   from the start of the fade down to `t_silence_onset`.
"""

import os
import logging
import soundfile as sf
import numpy as np
import librosa
from dataclasses import dataclass, field
from typing import Tuple, Dict, Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class VolumeEnvelopeProfile:
    """
    Container for extracted volume envelope metadata and fade curve.
    """
    total_duration_sec: float
    sample_rate: int
    t_silence_onset_sec: float
    t_silence_onset_sample: int
    fade_start_sec: float
    fade_start_sample: int
    fade_duration_sec: float
    noise_floor_db: float
    noise_floor_margin_db: float
    active_speech_peak_db: float
    fade_curve_array: np.ndarray = field(repr=False)
    envelope_times: np.ndarray = field(repr=False)
    envelope_db: np.ndarray = field(repr=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_duration_sec": round(self.total_duration_sec, 4),
            "sample_rate": self.sample_rate,
            "t_silence_onset_sec": round(self.t_silence_onset_sec, 4),
            "t_silence_onset_sample": self.t_silence_onset_sample,
            "fade_start_sec": round(self.fade_start_sec, 4),
            "fade_start_sample": self.fade_start_sample,
            "fade_duration_sec": round(self.fade_duration_sec, 4),
            "noise_floor_db": round(self.noise_floor_db, 2),
            "noise_floor_margin_db": round(self.noise_floor_margin_db, 2),
            "active_speech_peak_db": round(self.active_speech_peak_db, 2),
            "fade_curve_length": len(self.fade_curve_array)
        }


class RMSEnvelopeTracker:
    """
    48kHz High-Precision Volume Envelope Tracker & Fade Extractor.
    """
    def __init__(
        self,
        window_ms: float = 50.0,
        hop_ms: float = 10.0,
        margin_above_noise_db: float = 6.0,
        fade_search_tail_sec: float = 8.0,
        min_fade_dur_sec: float = 0.5
    ):
        self.window_ms = window_ms
        self.hop_ms = hop_ms
        self.margin_above_noise_db = margin_above_noise_db
        self.fade_search_tail_sec = fade_search_tail_sec
        self.min_fade_dur_sec = min_fade_dur_sec

    def analyze(self, audio_path_or_array, sr: int = 48000) -> VolumeEnvelopeProfile:
        """
        Analyzes audio at 48kHz and extracts the fade-out envelope.
        """
        if isinstance(audio_path_or_array, str):
            audio, orig_sr = sf.read(audio_path_or_array, dtype="float32")
            if len(audio.shape) > 1:
                audio = np.mean(audio, axis=1)
            if orig_sr != sr:
                audio = librosa.resample(audio, orig_sr=orig_sr, target_sr=sr)
        else:
            audio = np.asarray(audio_path_or_array, dtype="float32")
            if len(audio.shape) > 1:
                audio = np.mean(audio, axis=1)

        total_samples = len(audio)
        total_dur = total_samples / sr

        frame_len = int((self.window_ms / 1000.0) * sr)
        hop_len = int((self.hop_ms / 1000.0) * sr)

        # 1. Compute rolling RMS energy across 48kHz waveform
        rms = librosa.feature.rms(
            y=audio,
            frame_length=frame_len,
            hop_length=hop_len,
            center=True
        )[0]

        # Convert to dBFS
        rms_db = 20.0 * np.log10(np.maximum(rms, 1e-8))
        times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=hop_len)

        # 2. Establish noise floor & thresholds
        # Noise floor is estimated from bottom 15th percentile of the energy distribution
        noise_floor_db = float(np.percentile(rms_db, 15))
        threshold_silence_db = noise_floor_db + self.margin_above_noise_db

        # Active speech peak (95th percentile)
        speech_peak_db = float(np.percentile(rms_db, 95))

        # 3. Identify t_silence_onset (scanning backwards from end)
        search_start_time = max(0.0, total_dur - self.fade_search_tail_sec)
        search_start_idx = int(np.searchsorted(times, search_start_time))

        t_silence_onset = total_dur
        silence_frame_idx = len(times) - 1

        # Scan backwards from the very end of the file
        for i in range(len(rms_db) - 1, search_start_idx, -1):
            if rms_db[i] > threshold_silence_db:
                # Found the last active energy frame before total drop
                silence_frame_idx = min(i + 1, len(times) - 1)
                t_silence_onset = float(times[silence_frame_idx])
                break

        # Fallback if audio never dropped
        if t_silence_onset >= total_dur:
            t_silence_onset = total_dur

        # 4. Discover fade_start_time (where volume begins its terminal descent)
        # Look backwards from silence_frame_idx for the onset of the drop
        fade_start_time = max(0.0, t_silence_onset - 2.0)  # default 2s fade window
        fade_start_idx = max(0, int(np.searchsorted(times, fade_start_time)))

        for j in range(silence_frame_idx, search_start_idx, -1):
            # If energy rises back near normal speech level (within 10dB of peak)
            if rms_db[j] >= (speech_peak_db - 10.0):
                fade_start_idx = j
                fade_start_time = float(times[fade_start_idx])
                break

        fade_dur = max(0.05, t_silence_onset - fade_start_time)
        if fade_dur < self.min_fade_dur_sec:
            # Expand fade start slightly to ensure smooth curve
            fade_start_time = max(0.0, t_silence_onset - self.min_fade_dur_sec)
            fade_dur = t_silence_onset - fade_start_time

        fade_start_sample = int(fade_start_time * sr)
        silence_onset_sample = int(min(t_silence_onset * sr, total_samples))

        # 5. Extract Normalized fade_curve_array (sample-by-sample multiplier 1.0 -> 0.0)
        fade_sample_len = max(1, silence_onset_sample - fade_start_sample)
        fade_audio_slice = np.abs(audio[fade_start_sample:silence_onset_sample])

        # Smooth envelope curve using low-pass / monotonic decay fit
        # We compute the local RMS envelope and normalize from 1.0 to 0.0
        fade_curve_raw = np.linspace(1.0, 0.0, fade_sample_len, dtype=np.float32)
        
        # If real fade audio slice exists, modulate the linear ramp with actual envelope
        if len(fade_audio_slice) > 100:
            env_hop = max(1, int(sr * 0.005))  # 5ms smoothing
            env_smooth = librosa.feature.rms(
                y=fade_audio_slice,
                frame_length=min(len(fade_audio_slice), int(sr * 0.02)),
                hop_length=env_hop,
                center=True
            )[0]
            if len(env_smooth) > 1:
                pk_env = np.max(env_smooth) + 1e-8
                norm_env = np.interp(
                    np.linspace(0, 1, fade_sample_len),
                    np.linspace(0, 1, len(env_smooth)),
                    env_smooth / pk_env
                )
                # Combine smoothed real envelope with boundary-guaranteed decay
                fade_curve_array = np.clip(norm_env * np.linspace(1.0, 0.0, fade_sample_len), 0.0, 1.0).astype(np.float32)
                fade_curve_array[0] = 1.0
                fade_curve_array[-1] = 0.0
            else:
                fade_curve_array = fade_curve_raw
        else:
            fade_curve_array = fade_curve_raw

        logger.info(
            f"[ENVELOPE TRACKER] 48kHz Track Duration: {total_dur:.3f}s | "
            f"Silence Onset: {t_silence_onset:.3f}s | Fade Start: {fade_start_time:.3f}s "
            f"({fade_dur:.3f}s fade) | Noise Floor: {noise_floor_db:.1f} dBFS"
        )

        return VolumeEnvelopeProfile(
            total_duration_sec=total_dur,
            sample_rate=sr,
            t_silence_onset_sec=t_silence_onset,
            t_silence_onset_sample=silence_onset_sample,
            fade_start_sec=fade_start_time,
            fade_start_sample=fade_start_sample,
            fade_duration_sec=fade_dur,
            noise_floor_db=noise_floor_db,
            noise_floor_margin_db=self.margin_above_noise_db,
            active_speech_peak_db=speech_peak_db,
            fade_curve_array=fade_curve_array,
            envelope_times=times,
            envelope_db=rms_db
        )


def track_volume_envelope(input_wav_path: str, sr: int = 48000) -> VolumeEnvelopeProfile:
    """
    Convenience functional API for Module 1.
    """
    tracker = RMSEnvelopeTracker()
    return tracker.analyze(input_wav_path, sr=sr)
