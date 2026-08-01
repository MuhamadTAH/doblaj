import os
import re
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Pird: validate speaker_id before using it in file paths. speaker_id flows
# from user-controlled state.json into Path(); without this a crafted value
# like "../../../tmp/x" escapes the work_dir. See
# handoffs/dubbing-security-pass3-fixes.md Fix 5.
SPEAKER_ID_RE = re.compile(r"^[A-Za-z0-9_]{1,16}$")


def extract_speaker_references(chunks: list, work_dir: str) -> dict:
    """
    Phase 4: For each unique speaker ID in the transcribed chunks,
    find their longest chunk and extract a reference clip.
    
    target_duration_ms = min(5000, chunk_duration_ms)
    Saves as speaker_ref_{A}.wav, speaker_ref_{B}.wav, etc.
    
    Returns: dict mapping speaker_id -> reference wav path
    """
    speaker_candidates = {}
    
    # 1. Group all valid chunks by speaker
    for chunk in chunks:
        speaker = chunk.get("speaker", "A")
        audio_file = chunk.get("audio_file", "")
        duration = chunk.get("duration_sec", chunk.get("speech_duration", 0.0))
        has_collision = chunk.get("has_collision", False)
        
        if not audio_file or not os.path.exists(audio_file):
            continue
            
        if speaker not in speaker_candidates:
            speaker_candidates[speaker] = []
            
        speaker_candidates[speaker].append({
            "audio_file": audio_file,
            "duration": duration,
            "has_collision": has_collision,
            "chunk_id": chunk.get("chunk_id", "unknown"),
            "kurdish_raw": chunk.get("kurdish_raw", "")
        })
        
    references = {}
    for speaker_id, candidates in speaker_candidates.items():
        # 2. Quarantine Filter: Only pristine chunks (no collisions)
        pristine_chunks = [c for c in candidates if not c["has_collision"]]
        
        # Sort by duration DESC
        pristine_chunks.sort(key=lambda x: x["duration"], reverse=True)
        
        best_chunk = None
        if pristine_chunks:
            best_chunk = pristine_chunks[0]
            if best_chunk["duration"] < 5.0:
                logger.warning(
                    "[VOICE-ROUTER] QUARANTINE WARN: Best pristine chunk for %s is very short (%.2fs). Profile may be unstable.",
                    speaker_id, best_chunk["duration"]
                )
            else:
                logger.info(
                    "[VOICE-ROUTER] QUARANTINE LOCKED ✓ | speaker=%s | chunk=%s | duration=%.2fs",
                    speaker_id, best_chunk["chunk_id"], best_chunk["duration"]
                )
        else:
            # 3. Fallback if no pristine chunk exists
            candidates.sort(key=lambda x: x["duration"], reverse=True)
            best_chunk = candidates[0] if candidates else None
            if best_chunk:
                logger.error(
                    "[VOICE-ROUTER] QUARANTINE BLOCKED: Speaker %s has NO pristine chunks! "
                    "Falling back to longest collision chunk %s (%.2fs). TTS PROFILE WILL LIKELY BE CORRUPTED BY BLEED.",
                    speaker_id, best_chunk["chunk_id"], best_chunk["duration"]
                )
        
        if not best_chunk:
            continue
            
        # 4. Extract Smart Safe Core (Micro-VAD Guided)
        target_duration_sec = min(5.0, best_chunk["duration"])
        # Pird: validate speaker_id before path join. See Fix 5.
        if not isinstance(speaker_id, str) or not SPEAKER_ID_RE.match(speaker_id):
            raise ValueError(f"invalid speaker_id: {speaker_id!r}")
        ref_path = os.path.join(work_dir, f"speaker_ref_{speaker_id}.wav")
        
        try:
            # Load Audio for VAD
            import torch
            import soundfile as sf
            data, sr = sf.read(best_chunk["audio_file"])
            if len(data.shape) > 1:
                data = data.mean(axis=1)  # downmix stereo to mono
            data = data.reshape(1, -1)
            wav = torch.from_numpy(data).float()
            
            # Load VAD Model
            model, utils = torch.hub.load(
                repo_or_dir='snakers4/silero-vad',
                model='silero_vad',
                force_reload=False,
                trust_repo=True
            )
            (get_speech_timestamps, _, _, _, _) = utils
            
            timestamps = get_speech_timestamps(
                wav, model, sampling_rate=16000, min_silence_duration_ms=105
            )
            
            # Smart Selection: Skip the first block (likely bleed) and pick contiguous blocks
            # Pird: safe timestamp dict indexing. See Fix 13.
            if not timestamps:
                raise ValueError("VAD returned no speech timestamps")
            if len(timestamps) >= 2:
                ts1 = timestamps[1]
                if "start" not in ts1 or "end" not in timestamps[-1]:
                    raise ValueError("VAD timestamps missing 'start' or 'end'")
                # Start at block 1 to avoid the boundary bleed
                start_sample = ts1["start"]
                end_sample = timestamps[-1]["end"]
                
                # If duration is way too long, cut it at a later silence
                accumulated_duration = 0.0
                for i in range(1, len(timestamps)):
                    accumulated_duration = (timestamps[i]['end'] - start_sample) / 16000.0
                    if accumulated_duration >= target_duration_sec:
                        end_sample = timestamps[i]['end']
                        break
            elif len(timestamps) == 1:
                ts0 = timestamps[0]
                if "start" not in ts0 or "end" not in ts0:
                    raise ValueError("VAD timestamp missing 'start' or 'end'")
                start_sample = ts0["start"]
                end_sample = ts0["end"]
            else:
                # Fallback to math
                start_sample = int(max(0, (best_chunk["duration"] - target_duration_sec) / 2.0) * 16000)
                end_sample = start_sample + int(target_duration_sec * 16000)
                
            # Add 100ms padding
            start_sec = max(0.0, (start_sample / 16000.0) - 0.1)
            end_sec = min(best_chunk["duration"], (end_sample / 16000.0) + 0.1)
            actual_target_duration = end_sec - start_sec
            
            subprocess.run([
                "ffmpeg", "-y", "-i", best_chunk["audio_file"],
                "-ss", f"{start_sec:.3f}",
                "-t", f"{actual_target_duration:.3f}",
                "-ar", "16000", "-ac", "1",
                ref_path
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            
            ref_text_path = os.path.join(work_dir, f"speaker_ref_{speaker_id}.txt")
            with open(ref_text_path, "w", encoding="utf-8") as f:
                f.write(best_chunk["kurdish_raw"])
            
            references[speaker_id] = ref_path
            logger.info(
                "[VOICE-ROUTER] Smart-Extracted reference for Speaker %s: %.2fs from %s (VAD guided)",
                speaker_id, actual_target_duration, os.path.basename(best_chunk["audio_file"])
            )
        except Exception as e:
            logger.error("[VOICE-ROUTER] Failed to extract reference for Speaker %s: %s", speaker_id, e)
    
    return references


def route_voice(chunk: dict, session_state: dict) -> tuple[str | None, str | None]:
    """
    Phase 4 State Machine: Determine which voice reference to use for TTS.
    
    Returns: (voice_library_id, reference_audio_path)
        - State A (Custom Clone): voice_library_id=None, reference_audio_path=uploaded WAV
        - State B (Library Voice): voice_library_id=selected_id, reference_audio_path=None
        - State C (Auto): voice_library_id=None, reference_audio_path=speaker_ref_{X}.wav
    """
    work_dir = session_state.get("work_dir", "")
    
    # State B: User selected a Fish Audio library voice
    selected_voice_id = session_state.get("selected_voice_id")
    if selected_voice_id:
        logger.info("[VOICE-ROUTER] State B: Library voice %s", selected_voice_id)
        return selected_voice_id, None
    
    # State A: User uploaded a custom voice clone WAV
    global_voice_ref = os.path.join(work_dir, "global_voice_ref.wav")
    if os.path.exists(global_voice_ref):
        logger.info("[VOICE-ROUTER] State A: Custom clone from global_voice_ref.wav")
        return None, global_voice_ref
    
    # State C: Auto — route by speaker ID
    speaker_id = chunk.get("speaker", "A")
    speaker_ref = os.path.join(work_dir, f"speaker_ref_{speaker_id}.wav")
    if os.path.exists(speaker_ref):
        logger.info("[VOICE-ROUTER] State C: Auto-routing Speaker %s", speaker_id)
        return None, speaker_ref
    
    # Ultimate fallback: use the chunk's own Kurdish audio as reference
    chunk_audio = chunk.get("audio_file", "")
    if chunk_audio and os.path.exists(chunk_audio):
        logger.warning("[VOICE-ROUTER] Fallback: Using chunk's own Kurdish audio as reference")
        return None, chunk_audio
    
    logger.error("[VOICE-ROUTER] No voice reference available for chunk %s", chunk.get("chunk_id"))
    return None, None
