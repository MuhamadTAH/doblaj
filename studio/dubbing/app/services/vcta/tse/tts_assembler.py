"""
tts_assembler.py — Module 3: Post-Synthesis Fade Mimicry & 48kHz Canvas Assembler
===================================================================================
1. Aligns synthesized Fish Audio / TTS speech on the 48kHz master canvas.
2. Applies the exact `fade_curve_array` (from Module 1 Envelope Tracker) directly to the
   amplitude of the synthesized speech at the exact temporal coordinates.
3. Ensures synthesized voices fade out naturally into silence, perfectly mirroring
   the human video editor's original creative volume envelope.
"""

import os
import logging
import soundfile as sf
import numpy as np
import librosa
from typing import List, Dict, Any, Optional, Union

from app.services.vcta.tse.envelope_tracker import VolumeEnvelopeProfile

logger = logging.getLogger(__name__)


class TTSCanvasAssembler:
    """
    48kHz Master Canvas Audio Assembler with Fade-Out Mimicry.
    """
    def __init__(self, sample_rate: int = 48000):
        self.sr = sample_rate

    def apply_fade_mimicry(
        self,
        audio_48k: np.ndarray,
        envelope_profile: VolumeEnvelopeProfile
    ) -> np.ndarray:
        """
        Applies the exact normalized fade curve array to the terminal speech portion.
        """
        out_audio = np.copy(audio_48k)
        fade_start_sample = envelope_profile.fade_start_sample
        silence_onset_sample = envelope_profile.t_silence_onset_sample
        fade_curve = envelope_profile.fade_curve_array

        if len(fade_curve) == 0:
            return out_audio

        total_samples = len(out_audio)
        f_start = min(fade_start_sample, total_samples)
        f_end = min(silence_onset_sample, total_samples)

        if f_start >= f_end or f_start >= total_samples:
            return out_audio

        fade_len = f_end - f_start
        # Interpolate curve if sample count differs slightly
        if len(fade_curve) != fade_len:
            curve_applied = np.interp(
                np.linspace(0, 1, fade_len),
                np.linspace(0, 1, len(fade_curve)),
                fade_curve
            ).astype(np.float32)
        else:
            curve_applied = fade_curve

        # Apply multiplier directly to amplitude
        out_audio[f_start:f_end] *= curve_applied

        # Zero-out anything after silence onset (mathematically dead)
        if f_end < total_samples:
            out_audio[f_end:] = 0.0

        logger.info(
            f"[FADE MIMICRY] Applied fade curve across samples [{f_start} -> {f_end}] "
            f"({f_start/self.sr:.3f}s -> {f_end/self.sr:.3f}s | {fade_len} samples)"
        )
        return out_audio

    def assemble_tts_track(
        self,
        tts_segments: List[Dict[str, Any]],
        total_duration_sec: float,
        envelope_profile: Optional[VolumeEnvelopeProfile] = None,
        output_wav_path: Optional[str] = None
    ) -> np.ndarray:
        """
        Assembles multiple TTS speech segments onto the 48kHz master canvas
        and applies volume envelope fade mimicry to the tail.

        tts_segments format:
        [
            {
                "audio_path_or_array": "path/to/fish_tts_segment1.wav",
                "start_sec": 1.50,
                "end_sec": 4.80 (optional)
            },
            ...
        ]
        """
        total_samples = int(total_duration_sec * self.sr)
        master_canvas = np.zeros(total_samples, dtype=np.float32)

        for idx, seg in enumerate(tts_segments, 1):
            audio_source = seg.get("audio_path_or_array") or seg.get("audio")
            start_sec = float(seg.get("start_sec") or seg.get("start") or 0.0)

            if isinstance(audio_source, str):
                seg_audio, orig_sr = sf.read(audio_source, dtype="float32")
                if len(seg_audio.shape) > 1:
                    seg_audio = np.mean(seg_audio, axis=1)
                if orig_sr != self.sr:
                    seg_audio = librosa.resample(seg_audio, orig_sr=orig_sr, target_sr=self.sr)
            else:
                seg_audio = np.asarray(audio_source, dtype="float32")
                if len(seg_audio.shape) > 1:
                    seg_audio = np.mean(seg_audio, axis=1)

            start_sample = int(start_sec * self.sr)
            end_sample = start_sample + len(seg_audio)

            if start_sample >= total_samples:
                continue

            available_len = min(len(seg_audio), total_samples - start_sample)
            master_canvas[start_sample:start_sample+available_len] += seg_audio[:available_len]

            logger.info(
                f"[TTS ASSEMBLE] Placed Segment #{idx} at {start_sec:.3f}s "
                f"({len(seg_audio)/self.sr:.3f}s dur)"
            )

        # Apply Fade Mimicry if envelope profile provided
        if envelope_profile is not None:
            master_canvas = self.apply_fade_mimicry(master_canvas, envelope_profile)

        # Normalize to broadcast standard (-1.0 dBFS)
        pk = float(np.max(np.abs(master_canvas)))
        if pk > 0.0:
            master_canvas = master_canvas * (0.89125 / pk)

        if output_wav_path:
            os.makedirs(os.path.dirname(output_wav_path), exist_ok=True)
            sf.write(output_wav_path, master_canvas, self.sr)
            logger.info(f"[TTS MASTER EXPORT] Saved -> {output_wav_path} ({len(master_canvas)/self.sr:.3f}s @ {self.sr}Hz)")

        return master_canvas


def assemble_and_mimic_tts_fade(
    tts_segments: List[Dict[str, Any]],
    total_duration_sec: float,
    envelope_profile: VolumeEnvelopeProfile,
    output_wav_path: str,
    sample_rate: int = 48000
) -> str:
    """
    Convenience Functional Entrypoint for Module 3.
    """
    assembler = TTSCanvasAssembler(sample_rate=sample_rate)
    assembler.assemble_tts_track(
        tts_segments=tts_segments,
        total_duration_sec=total_duration_sec,
        envelope_profile=envelope_profile,
        output_wav_path=output_wav_path
    )
    return output_wav_path
