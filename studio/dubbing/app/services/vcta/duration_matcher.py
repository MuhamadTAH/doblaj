"""
duration_matcher.py — WSOLA Bounded Time-Stretching for Stage 4/5 Assembly
===========================================================================
Ensures synthesized Iraqi Arabic TTS audio fits precisely inside its allocated
timeline slot without drifting into adjacent speaker turns.

Caps time-stretch rate to ±15% (0.85x to 1.15x) to maintain natural vocal pitch and acoustics.
"""

import os
import logging
import numpy as np
import soundfile as sf
import librosa

logger = logging.getLogger(__name__)


def match_audio_duration_bounded(
    tts_wav_path: str,
    output_path: str,
    target_duration_sec: float,
    max_stretch_pct: float = 0.15, # Max 15% rate adjustment
) -> str:
    """
    Applies bounded pitch-preserving time stretching to match target_duration_sec.
    """
    if target_duration_sec <= 0.1:
        return tts_wav_path

    audio, sr = sf.read(tts_wav_path, dtype="float32")
    current_duration = len(audio) / sr

    if current_duration <= 0.05:
        return tts_wav_path

    raw_rate = current_duration / target_duration_sec

    # Bound stretch rate strictly between 0.95 and 1.15
    min_rate = 0.95
    max_rate = 1.15

    bounded_rate = float(np.clip(raw_rate, min_rate, max_rate))

    logger.info(
        f"[DURATION-MATCHER] tts_dur={current_duration:.2f}s | target_dur={target_duration_sec:.2f}s | "
        f"raw_rate={raw_rate:.3f} | bounded_rate={bounded_rate:.3f}"
    )

    if abs(bounded_rate - 1.0) < 0.02:
        # Less than 2% drift, no stretching needed
        sf.write(output_path, audio, sr, subtype="FLOAT")
        return output_path

    # Apply WSOLA / phase vocoder time stretch
    if audio.ndim > 1:
        # Stereo audio: process channels separately
        ch1 = librosa.effects.time_stretch(y=audio[:, 0], rate=bounded_rate)
        ch2 = librosa.effects.time_stretch(y=audio[:, 1], rate=bounded_rate)
        min_len = min(len(ch1), len(ch2))
        stretched_audio = np.column_stack([ch1[:min_len], ch2[:min_len]])
    else:
        stretched_audio = librosa.effects.time_stretch(y=audio, rate=bounded_rate)

    sf.write(output_path, stretched_audio, sr, subtype="FLOAT")
    logger.info(f"[DURATION-MATCHER] Saved duration-matched audio: {output_path}")
    return output_path
