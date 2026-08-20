"""
assembler.py — Final Video Assembly Engine (Stage 5)
Uses absolute timeline assembly against a silent master track.
"""
import os
import logging
import asyncio
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def _get_wav_duration_sync(wav_path: str) -> float:
    """Sync ffprobe helper — wrap calls in asyncio.to_thread from async code."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                wav_path,
            ],
            capture_output=True, text=True, check=True,
        )
        return float(result.stdout.strip())
    except Exception as e:
        logger.error("[ASSEMBLER] ffprobe failed for %s: %s", wav_path, e)
        return 0.0

async def assemble_final_video(
    chunks: list,
    background_wav: str,
    video_path: str,
    work_dir: str,
    reference_profile: dict = None,
    purged_secondary_turns: list = None,
    isolated_vocal_wav: str = None,
) -> str:
    """
    Stage 5: The FFmpeg Timeline Assembly (The Pause Math)
    Creates a master silent track, maps all clips using adelay, and merges.
    Integrates Numpy Secondary Speaker Restoration prior to reference mastering.
    """
    work = Path(work_dir)
    tts_entries = []

    # If purged secondary turns exist, run Secondary Speaker Restoration on background stem first
    if purged_secondary_turns and isolated_vocal_wav and os.path.exists(isolated_vocal_wav):
        from app.services.vcta.restoration import restore_secondary_vocals
        restored_bg_path = str(work / "Audio_3_Noise_Restored.wav")
        logger.info(f"[ASSEMBLER] Restoring {len(purged_secondary_turns)} purged secondary turns back to background stem...")
        try:
            background_wav = restore_secondary_vocals(
                instrumental_path=background_wav,
                vocals_path=isolated_vocal_wav,
                purged_turns=purged_secondary_turns,
                output_path=restored_bg_path,
                fade_ms=50
            )
        except Exception as e:
            logger.error(f"[ASSEMBLER] Secondary vocal restoration failed: {e}. Falling back to raw background stem.")
    
    if not chunks:
        raise RuntimeError("No chunks were provided to the assembler. Upstream processing likely failed on all chunks.")
    
    for enumerate_idx, chunk in enumerate(chunks, start=1):
        tts_file = chunk.get("tts_file", "")
        if not tts_file or not os.path.exists(tts_file):
            chunk_id = chunk.get('chunk_id')
            idx = chunk.get('chunk_index', enumerate_idx)
            
            assembled_atempo = work / "assembled" / f"chunk_{chunk_id}_assembled.wav"
            mastered = work / "mastered_chunks" / f"chunk_{idx}_mastered.wav"
            raw_tts = work / "tts" / f"raw_tts_{chunk_id}.wav"
            
            if assembled_atempo.exists():
                tts_file = str(assembled_atempo)
            elif mastered.exists():
                tts_file = str(mastered)
            elif raw_tts.exists():
                tts_file = str(raw_tts)
            else:
                logger.warning(f"[ASSEMBLER] Could not find any TTS file for chunk {chunk_id}. Checked paths:\n- {assembled_atempo}\n- {mastered}\n- {raw_tts}")
                continue

        start_time = float(chunk.get("start_time", 0.0))
        tts_entries.append({
            "chunk_id": chunk.get("chunk_id"),
            "tts_file": tts_file,
            "start_time_ms": int(start_time * 1000),
        })

    if not tts_entries:
        errors = [c.get("error") or c.get("tts_error") for c in chunks if isinstance(c, dict) and (c.get("error") or c.get("tts_error"))]
        if errors:
            unique_errors = list(set(errors))
            raise RuntimeError(f"No TTS files were generated. TTS API Errors: {', '.join(unique_errors)}")
        raise RuntimeError("No TTS files found for any chunk. Cannot assemble video.")

    bg_exists = os.path.exists(background_wav)
    bg_size = os.path.getsize(background_wav) if bg_exists else 0
    video_exists = os.path.exists(video_path)
    logger.info(f"[ASSEMBLER] Stage 5: Assembling {len(tts_entries)} clips against silent master. background_wav={background_wav} (exists={bg_exists}, size={bg_size}b), video_path={video_path} (exists={video_exists})")

    # Get total video duration to create the silent master
    video_duration = await asyncio.to_thread(_get_wav_duration_sync, video_path)
    if video_duration == 0.0:
        video_duration = await asyncio.to_thread(_get_wav_duration_sync, background_wav)
        
    silent_master_wav = str(work / "silent_master.wav")
    
    # Generate the completely silent master audio track
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", f"anullsrc=r=16000:cl=mono",
        "-t", str(video_duration), silent_master_wav
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    arabic_voice_wav = str(work / "arabic_vocal_full.wav")

    # Build the filtergraph to overlay clips on the silent master
    inputs = ["-i", silent_master_wav]
    filter_parts = []
    mix_inputs = ["[0:a]"]
    
    for i, entry in enumerate(tts_entries):
        inputs.extend(["-i", entry["tts_file"]])
        idx = i + 1  # Since 0 is silent master
        delay_ms = entry["start_time_ms"]
        
        # Delay the input clip
        delayed_label = f"[d{idx}]"
        filter_parts.append(f"[{idx}:a]adelay={delay_ms}|{delay_ms}{delayed_label}")
        mix_inputs.append(delayed_label)
        
    # Mix all at once to prevent volume halving. 
    # Removed `apad` to prevent the infinite silence generation bug. `duration=first` bounds it correctly.
    filter_parts.append(f"{''.join(mix_inputs)}amix=inputs={len(mix_inputs)}:duration=first:dropout_transition=0:normalize=0[aout]")
    
    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", ";".join(filter_parts),
        "-map", "[aout]",
        "-ac", "1", "-ar", "16000",
        arabic_voice_wav
    ]
    
    logger.info("[ASSEMBLER] Concatenating Arabic vocals...")
    ffmpeg_log = work / "ffmpeg_concat.log"
    with open(ffmpeg_log, "w") as f_err:
        result = await asyncio.to_thread(
            subprocess.run, cmd,
            stdout=subprocess.DEVNULL, stderr=f_err
        )
    
    if result.returncode != 0:
        with open(ffmpeg_log, "r") as f_err:
            err_output = f_err.read()
        logger.error(f"[ASSEMBLER] Concatenation failed: {err_output[-1000:]}")
        raise RuntimeError(f"FFmpeg failed to build Arabic voice track")
        
    logger.info("[ASSEMBLER] Arabic voice track created (absolute anchors): %s", arabic_voice_wav)
    
    # Mix Arabic dialogue with background SFX/music via Broadcast DialogueDucker
    final_output_path = str(work / "assembled" / "final_dubbed.mp4")
    Path(final_output_path).parent.mkdir(parents=True, exist_ok=True)
    
    mastered_audio_wav = str(work / "assembled" / "mastered_audio_track.wav")
    from app.services.vcta.dialogue_ducker import stream_mix_dialogue
    
    logger.info("[ASSEMBLER] Stage 5: Fusing Dialogue and Background stems via Broadcast DialogueDucker...")
    await asyncio.to_thread(
        stream_mix_dialogue,
        track_a_path=arabic_voice_wav,
        track_b_path=background_wav,
        output_path=mastered_audio_wav,
        ducking_db=-4.5,
        target_ceiling_db=-1.0,
    )

    # Multiplex the EBU R128 True-Peak mastered audio track with the video
    logger.info("[ASSEMBLER] Muxing mastered audio with video stream...")
    mux_cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", mastered_audio_wav,
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "48000",
        "-movflags", "+faststart",
        final_output_path
    ]
    
    mux_result = await asyncio.to_thread(
        subprocess.run, mux_cmd,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True
    )
    
    if mux_result.returncode != 0:
        logger.error("[ASSEMBLER] Video multiplexing failed: %s", mux_result.stderr[-1000:])
        raise RuntimeError("FFmpeg failed to mux final video with mastered audio")
        
    logger.info("[ASSEMBLER] Final dubbed video successfully produced at: %s", final_output_path)
    return final_output_path

