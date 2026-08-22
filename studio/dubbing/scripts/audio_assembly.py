import os
import shutil
import subprocess
import wave
import contextlib
import logging
import ffmpeg
import numpy as np

logger = logging.getLogger(__name__)


def get_pre_split_segments(arabic_text: str, total_duration: float, rolling_cps: float) -> list[str]:
    """
    Determines if the Arabic text should be pre-split into smaller TTS segments
    based on the 1.0s clip guardrail: if the estimated TTS duration for the text
    exceeds the total slot by more than 1.0s, split into smaller pieces.

    Returns a list of text segments (usually 1 or 2).
    """
    if not arabic_text.strip():
        return [arabic_text]

    estimated_duration = len(arabic_text) / max(rolling_cps, 1.0)

    # If text fits comfortably, don't split
    if estimated_duration <= total_duration + 1.0:
        return [arabic_text]

    # Split by sentence-ending punctuation first
    import re
    sentences = re.split(r'(?<=[.،؟!])\s*', arabic_text)
    sentences = [s.strip() for s in sentences if s.strip()]

    if len(sentences) >= 2:
        mid = len(sentences) // 2
        part_a = " ".join(sentences[:mid])
        part_b = " ".join(sentences[mid:])
        return [part_a, part_b]

    # If no good split point, split at word boundary near the middle
    words = arabic_text.split()
    if len(words) >= 4:
        mid = len(words) // 2
        part_a = " ".join(words[:mid])
        part_b = " ".join(words[mid:])
        return [part_a, part_b]

    return [arabic_text]


class AudioAssembler:
    def __init__(self, target_duration: float):
        self.target_duration = target_duration

    def _get_wav_duration(self, wav_path: str) -> float:
        if not os.path.exists(wav_path):
            return 0.0
        try:
            probe = ffmpeg.probe(wav_path)
            # Find audio stream
            audio_stream = next((s for s in probe['streams'] if s['codec_type'] == 'audio'), None)
            if audio_stream and 'duration' in audio_stream:
                return float(audio_stream['duration'])
            elif 'format' in probe and 'duration' in probe['format']:
                return float(probe['format']['duration'])
        except Exception as e:
            logger.error(f"[AudioAssembler] Failed to get duration with ffprobe for {wav_path}: {e}")
            
        # Fallback to wave if ffprobe fails
        with contextlib.closing(wave.open(wav_path, 'r')) as f:
            frames = f.getnframes()
            rate = f.getframerate()
            return frames / float(rate)

    def _apply_atempo_stretch(self, input_wav: str, output_wav: str, speed_ratio: float) -> str:
        """
        Path A: Dynamically stretch or compress audio using atempo.
        """
        logger.info(f"[AudioAssembler] PATH A: Applying atempo for speed_ratio={speed_ratio:.4f} to match {self.target_duration}s.")
        try:
            from app.services.vcta.reference_mastering import build_atempo_chain
            atempo_chain = build_atempo_chain(speed_ratio)
            
            # Use raw ffmpeg command to apply the complex atempo chain since ffmpeg-python 
            # doesn't handle comma-separated custom filter chains well via .filter()
            cmd = [
                "ffmpeg", "-y", "-i", input_wav,
                "-af", atempo_chain,
                "-ar", "16000", "-ac", "1", output_wav
            ]
            import subprocess
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            
            # Phase 2: Dynamic Padding, Trimming, & The Guillotine
            actual_dur = self._get_wav_duration(output_wav)
            
            if actual_dur < self.target_duration:
                # The audio is short (hit the 0.95x floor). We must pad with silence.
                # Fade out the very end of the actual audio (40ms) to avoid popping before the digital silence.
                fade_start = max(0.0, actual_dur - 0.04)
                fade_dur = min(actual_dur, 0.04)
                filter_str = f"afade=t=out:st={fade_start}:d={fade_dur},apad"
            else:
                # The audio is long (hit the 1.20x ceiling). The guillotine will slice it at target_duration.
                # Fade out 50ms before the slice to hide the cut.
                fade_start = max(0.0, self.target_duration - 0.05)
                fade_dur = min(self.target_duration, 0.05)
                filter_str = f"afade=t=out:st={fade_start}:d={fade_dur}"

            # Ensure strict duration and apply the calculated fade/pad
            # Pird: list-args subprocess, no shell. See pass-6 review.
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-i", output_wav,
                    "-af", filter_str,
                    "-t", str(self.target_duration),
                    "-ar", "16000", "-ac", "1",
                    f"{output_wav}_strict.wav",
                ],
                shell=False, check=False,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            os.replace(f"{output_wav}_strict.wav", output_wav)
            return output_wav
        except Exception as e:
            logger.error(f"FFmpeg atempo failed: {e}")
            # Pird: shutil.copyfile replaces the Windows `os.system('copy ...')` shell call.
            shutil.copyfile(input_wav, output_wav)
            return output_wav

    def fit_audio(self, input_wav: str, output_wav: str, tolerance: float = 0.05) -> dict:
        """
        Fits the TTS audio into the exact target_duration slot using atempo.
        Any audio reaching this function has already passed the 0.82-1.20 Scale Ratio
        gate in manual_video.py.
        """
        tts_dur = self._get_wav_duration(input_wav)
        delta = tts_dur - self.target_duration

        path_taken = "A"
        if tts_dur <= 0.1 or self.target_duration <= 0.1:
            # Pird: shutil.copyfile replaces os.system('copy ...'). See pass-6.
            shutil.copyfile(input_wav, output_wav)
        elif abs(delta) <= tolerance:
            logger.info(f"[AudioAssembler] PATH A: Perfect Fit (delta={delta:.3f}s)")
            if delta > 0.02:
                # Apply micro-atempo to fit 100% of speech rather than cutting
                micro_ratio = tts_dur / self.target_duration
                self._apply_atempo_stretch(input_wav, output_wav, micro_ratio)
            else:
                shutil.copyfile(input_wav, output_wav)
        else:
            speed_ratio = tts_dur / self.target_duration
            
            # Clamp speed_ratio strictly between 0.95x and 1.15x
            if speed_ratio < 0.95:
                logger.info(f"[AudioAssembler] Clamping slowdown {speed_ratio:.3f} -> 0.95")
                speed_ratio = 0.95
                
            if speed_ratio > 1.15:
                logger.warning(f"[AudioAssembler] Speedup exceeds 1.15x ({speed_ratio:.3f}) -> Capping at 1.15x")
                speed_ratio = 1.15
                
            self._apply_atempo_stretch(input_wav, output_wav, speed_ratio)

        return {
            "path_taken": path_taken,
            "tts_duration": tts_dur,
            "target_duration": self.target_duration,
            "delta": delta
        }

async def process_chunk_assembly(chunk: dict, tts_dir: str, output_dir: str, rolling_cps: float, padding_debt_ms: float, target_active_duration: float = None) -> tuple:
    """
    Main async orchestrator for a single chunk's audio assembly.
    Updates rolling CPS and padding debt.
    Returns: (updated_chunk, assembled_path, updated_cps, updated_debt_ms)
    """
    chunk_id = chunk.get("chunk_id", "unknown")
    total_duration = float(chunk.get("total_duration", 0))
    speech_duration = target_active_duration if target_active_duration is not None else float(chunk.get("speech_duration", 0))
    
    # Debt recovery: if we have debt, we can stretch the target duration slightly
    padding_debt_sec = padding_debt_ms / 1000.0
    target_dur = speech_duration + padding_debt_sec
    
    assembler = AudioAssembler(target_duration=target_dur)
    
    raw_tts_wav = os.path.join(tts_dir, f"raw_tts_{chunk_id}.wav")
    output_wav = os.path.join(output_dir, f"tts_{chunk_id}.wav")
    
    stats = assembler.fit_audio(raw_tts_wav, output_wav)
    
    # Calculate rolling CPS
    actual_tts_dur = stats["tts_duration"]
    arabic_text = chunk.get("arabic_text", "")
    char_count = len(arabic_text)
    
    new_cps = rolling_cps
    if actual_tts_dur > 0 and char_count > 0:
        chunk_cps = char_count / actual_tts_dur
        new_cps = (rolling_cps * 0.7) + (chunk_cps * 0.3)
        
    # Calculate new padding debt
    new_debt = 0.0
    if stats["path_taken"] == "B":
        new_debt = min(1.0, padding_debt_sec + abs(stats["delta"]))
    elif stats["path_taken"] == "C":
        new_debt = 0.0 # Debt wiped
        
    # Update chunk status
    chunk["status"] = "tts_done"
    chunk["path_taken"] = stats["path_taken"]
    chunk["tts_duration"] = actual_tts_dur
    chunk["delta"] = stats["delta"]
    
    return chunk, output_wav, new_cps, new_debt * 1000.0
