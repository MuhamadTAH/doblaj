"""
master_assembler.py — Module 5: Timed Multi-Track Canvas Assembly
==================================================================
Maintains zero-filled full-length numpy audio arrays for Track_Host and Track_Vendor
at 48kHz studio sample rate based on original video duration:
1. Inserts synthesized Arabic TTS audio at sample index int(start_sec * 48000).
2. Applies pitch-neutral WSOLA time-stretching if TTS duration differs from slot by ±15%.
3. Mixes Track_Host and Track_Vendor with M&E track using dialogue ducking.
"""

import os
import logging
import soundfile as sf
import numpy as np
import librosa
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class MasterCanvasAssembler:
    """Multi-Track 48kHz Studio Audio Canvas Assembler."""

    def __init__(self, total_duration_sec: float, sample_rate: int = 48000):
        self.total_duration_sec = total_duration_sec
        self.sample_rate = sample_rate
        self.total_samples = int(total_duration_sec * sample_rate)

        # Zero-filled stereo canvas tracks for Host and Vendor
        self.track_host = np.zeros((self.total_samples, 2), dtype=np.float32)
        self.track_vendor = np.zeros((self.total_samples, 2), dtype=np.float32)

    def insert_tts_segment(
        self,
        speaker_id: str,
        tts_wav_path: str,
        start_sec: float,
        target_slot_duration: float
    ) -> bool:
        """
        Inserts synthesized TTS audio into its designated track.
        Applies WSOLA time-stretching if duration differs by ±15%.
        """
        if not os.path.exists(tts_wav_path):
            logger.error(f"[CANVAS-ASSEMBLER] TTS file missing: {tts_wav_path}")
            return False

        tts_data, sr = sf.read(tts_wav_path, dtype="float32")
        if len(tts_data) == 0:
            return False

        # Resample to canvas sample rate (48kHz) if needed
        if sr != self.sample_rate:
            if len(tts_data.shape) > 1:
                tts_data = tts_data.mean(axis=1)
            tts_data = librosa.resample(tts_data, orig_sr=sr, target_sr=self.sample_rate)

        # Convert mono to stereo if needed
        if len(tts_data.shape) == 1:
            tts_data = np.column_stack([tts_data, tts_data])

        tts_duration = len(tts_data) / self.sample_rate

        # WSOLA Time-Stretching Rule: If duration differs by > ±15%
        if target_slot_duration > 0.2:
            ratio = tts_duration / target_slot_duration
            if abs(ratio - 1.0) > 0.15:
                # Clamp stretching ratio strictly between 0.95x and 1.15x
                stretch_rate = max(0.95, min(1.15, ratio))
                logger.info(f"[WSOLA-STRETCH] Stretching {speaker_id} TTS: {tts_duration:.2f}s -> {target_slot_duration:.2f}s (Rate: {stretch_rate:.2f}x)")

                left = librosa.effects.time_stretch(tts_data[:, 0], rate=stretch_rate)
                right = librosa.effects.time_stretch(tts_data[:, 1], rate=stretch_rate)
                tts_data = np.column_stack([left, right])

        start_sample = int(start_sec * self.sample_rate)
        num_samples = len(tts_data)
        end_sample = min(start_sample + num_samples, self.total_samples)

        valid_len = end_sample - start_sample
        if valid_len <= 0:
            return False

        # Insert into designated canvas track
        if speaker_id in ("Speaker_A", "SPEAKER_00", "host"):
            self.track_host[start_sample:end_sample] += tts_data[:valid_len]
        else:
            self.track_vendor[start_sample:end_sample] += tts_data[:valid_len]

        logger.info(
            f"[CANVAS-ASSEMBLER] Placed {speaker_id} TTS into Canvas: "
            f"Start: {start_sec:.2f}s | Samples: {start_sample} -> {end_sample}"
        )
        return True

    def export_tracks(self, output_dir: str) -> Dict[str, str]:
        """Exports the full 48kHz Host and Vendor tracks to WAV files."""
        os.makedirs(output_dir, exist_ok=True)
        host_file = os.path.join(output_dir, "master_track_host_48k.wav")
        vendor_file = os.path.join(output_dir, "master_track_vendor_48k.wav")

        sf.write(host_file, self.track_host, self.sample_rate)
        sf.write(vendor_file, self.track_vendor, self.sample_rate)

        return {
            "track_host": host_file,
            "track_vendor": vendor_file
        }

    def mix_master_audio(
        self,
        bg_m_and_e_path: Optional[str],
        output_master_path: str,
        ducking_db: float = -12.0
    ) -> str:
        """
        Mixes Track_Host and Track_Vendor over Background Music & Effects (M&E)
        with automatic dialogue ducking.
        """
        dialogue_mix = self.track_host + self.track_vendor

        if bg_m_and_e_path and os.path.exists(bg_m_and_e_path):
            mne_data, sr = sf.read(bg_m_and_e_path, dtype="float32")
            if sr != self.sample_rate:
                if len(mne_data.shape) > 1: mne_data = mne_data.mean(axis=1)
                mne_data = librosa.resample(mne_data, orig_sr=sr, target_sr=self.sample_rate)
            if len(mne_data.shape) == 1:
                mne_data = np.column_stack([mne_data, mne_data])

            # Truncate / pad to matching length
            min_len = min(len(dialogue_mix), len(mne_data))

            # Apply Dialogue Ducking: Reduce M&E volume when dialogue is active
            diag_envelope = np.max(np.abs(dialogue_mix[:min_len]), axis=1)
            duck_factor = np.where(diag_envelope > 0.02, 10.0 ** (ducking_db / 20.0), 1.0)
            ducked_mne = mne_data[:min_len] * duck_factor[:, None]

            final_master = dialogue_mix[:min_len] + ducked_mne
        else:
            final_master = dialogue_mix

        # Normalize audio peak to -1.0 dB to prevent clipping
        max_val = np.max(np.abs(final_master))
        if max_val > 0.95:
            final_master = final_master * (0.95 / max_val)

        os.makedirs(os.path.dirname(output_master_path), exist_ok=True)
        sf.write(output_master_path, final_master, self.sample_rate)

        logger.info(f"[MASTER-ASSEMBLER] Final Master Audio Exported: {output_master_path}")
        return output_master_path
