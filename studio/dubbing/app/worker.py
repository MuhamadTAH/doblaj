import os
from dotenv import load_dotenv
load_dotenv()
import asyncio
import logging
from celery import Celery, chord
from redis import Redis
import shutil
import subprocess
from pathlib import Path
import math
from pydub import AudioSegment
from pydub.silence import detect_leading_silence

# Adjust paths to match imports
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.vcta.translator import translate_single_chunk_structured
from app.services.vcta.tts_engine import generate_tts, _get_audio_duration
from app.services.vcta.voice_router import route_voice
from scripts.audio_assembly import process_chunk_assembly
from app.services.vcta.assembler import assemble_final_video
from app.core.database import update_job_status, get_job
from app.core.session_logger import session_log_context

try:
    from app.core.pipeline_tracer import trace_step
except ImportError:
    def trace_step(*a, **kw): pass

# Pird: validate chunk_id before using it to construct file paths. chunk_id
# flows from user-controlled state.json into Path() — without this, a
# crafted chunk_id like "../../etc/passwd" escapes the session dir. See
# handoffs/dubbing-security-pass2-fixes.md Fix 3.
import re as _re
CHUNK_ID_RE = _re.compile(r"^[A-Za-z0-9_-]{1,64}$")

logger = logging.getLogger(__name__)

# Pird: Redis URL must come from env. No default — refuse to start with an
# unauthenticated localhost Redis in any environment. See
# handoffs/dubbing-security-pass2-fixes.md Fix 1.
REDIS_URL = os.getenv("REDIS_URL")
if not REDIS_URL:
    raise RuntimeError(
        "REDIS_URL must be set; refusing to start with default unauthenticated Redis"
    )

# Initialize Redis client for circuit breaker state
redis_client = Redis.from_url(REDIS_URL, decode_responses=True)

# Initialize Celery app
celery = Celery(
    'dubbing_worker',
    broker=REDIS_URL,
    backend=REDIS_URL
)
celery.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
)

class CriticalHaltException(Exception):
    pass

@celery.task(bind=True, max_retries=0)
def process_chunk_task(self, chunk: dict, session_id: str, session_state_dict: dict, video_path: str):
    """
    Service B: The Pipeline Worker
    Executes Translation -> TTS -> FFmpeg Atempo for a specific chunk.
    """
    # Create an event loop for async functions
    with session_log_context(session_id):
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
        return loop.run_until_complete(_async_process_chunk(chunk, session_id, session_state_dict, video_path))

async def _async_process_chunk(chunk: dict, session_id: str, session_state_dict: dict, video_path: str, translate_only: bool = False, bypass_initial_translation: bool = False, remaster_only: bool = False, skip_math: bool = False):
    """
    Service B: The Processing Engine (Stage 2 + 3 + 4)
    Handles Transcreation, Evaluation, and Voice Routing.
    """
    chunk_id = chunk.get("chunk_id", "unknown")
    
    if not chunk.get("kurdish_raw") and not chunk.get("arabic_text") and not remaster_only:
        logger.warning(f"Chunk {chunk_id} has no kurdish_raw or arabic_text. Skipping processing.")
        return {"chunk_id": chunk_id, "status": "skipped", "error": chunk.get("error") or "No source text"}
    
    # Check circuit breaker before starting
    processed_key = f"circuit_breaker:{session_id}:processed"
    zone_c_key = f"circuit_breaker:{session_id}:zone_c"
    
    try:
        processed_count = int(redis_client.get(processed_key) or 0)
        zone_c_count = int(redis_client.get(zone_c_key) or 0)
    except Exception:
        processed_count = 0
        zone_c_count = 0
    
    if processed_count > 20 and (zone_c_count / processed_count) > 0.15:
        logger.error(f"[CIRCUIT BREAKER] Tripped for session {session_id}! Aborting task.")
        return {"chunk_id": chunk_id, "status": "failed", "error": "Circuit Breaker Tripped"}

    audio_path = chunk.get("audio_file")
    if not audio_path or not os.path.exists(audio_path):
        return {"chunk_id": chunk_id, "status": "skipped", "error": "No audio file"}
        
    try:
        from pydub import AudioSegment
        from app.services.vcta.audio_pipeline import detect_leading_silence
        
        vocal_path = chunk.get("vocal_file")
        if vocal_path and os.path.exists(vocal_path):
            source_audio = AudioSegment.from_file(vocal_path)
        from pydub.silence import detect_nonsilent
        orig_audio = AudioSegment.from_file(audio_path)
        total_duration_ms = len(orig_audio)
        
        # Use advanced VAD ML timestamps if available
        vad_start = chunk.get("vad_start")
        vad_end = chunk.get("vad_end")
        start_time = chunk.get("start_time", 0.0)
        end_time = chunk.get("end_time", total_duration_ms / 1000.0)
        
        if vad_start is not None and vad_end is not None:
            leading_silence_ms = int(max(0, vad_start - start_time) * 1000)
            trailing_silence_ms = int(max(0, end_time - vad_end) * 1000)
            active_duration_ms = int(max(0, vad_end - vad_start) * 1000)
        else:
            nonsilent_ranges = detect_nonsilent(orig_audio, min_silence_len=100, silence_thresh=-40.0)
            
            if not nonsilent_ranges:
                # 100% silent chunk
                return {"chunk_id": chunk_id, "status": "skipped", "error": "100% silent chunk"}
                
            leading_silence_ms = nonsilent_ranges[0][0]
            trailing_silence_ms = total_duration_ms - nonsilent_ranges[-1][1]
            active_duration_ms = nonsilent_ranges[-1][1] - nonsilent_ranges[0][0]
            
        active_duration_sec = active_duration_ms / 1000.0
    except Exception as e:
        logger.error(f"Failed to process silence detection: {e}")
        active_duration_sec = chunk.get("speech_duration", chunk.get("duration_sec", 0.0))
        leading_silence_ms = 0
        
    video_slot_duration = active_duration_sec
    if video_slot_duration <= 0:
        return {"chunk_id": chunk_id, "status": "skipped"}

    # Pipeline initialization
    padding_debt_ms = 0.0
    
    dir_arabic = Path("data/jobs/sessions") / session_id / "6-arabic_audio_chunks"
    dir_arabic.mkdir(parents=True, exist_ok=True)
    
    # Legacy dirs required by audio_assembly.py
    tts_dir = Path("data/jobs/sessions") / session_id / "tts"
    tts_dir.mkdir(parents=True, exist_ok=True)
    assembled_dir = Path("data/jobs/sessions") / session_id / "assembled"
    assembled_dir.mkdir(parents=True, exist_ok=True)
    
    final_tts_wav = str(tts_dir / f"raw_tts_{chunk_id}.wav")
    
    retries = 0
    max_retries = 3 if not translate_only else 0
    is_zone_c = False
    
    # 0. Set hardcoded 1.8 WPS as per the new Time-Aware Word Constraints directive
    current_wps = 1.8
    retry_prompt = None
    
    history_chunks = []
    try:
        import json
        state_path = Path("data/jobs/sessions") / session_id / "state.json"
        
        idx = chunk.get("chunk_index", 1)
        if state_path.exists():
            with open(state_path, "r", encoding="utf-8") as f:
                state_data = json.load(f)
                all_chunks = state_data.get("chunks", [])
                
                # Find current chunk index
                current_idx = -1
                for i, c in enumerate(all_chunks):
                    if c.get("chunk_id") == chunk_id:
                        current_idx = i
                        idx = i + 1
                        break
                
                if current_idx >= 0:
                    # Get N-2 and N-1 indices (skip if negative)
                    history_indices = [current_idx - 2, current_idx - 1]
                    for h_idx in history_indices:
                        if h_idx >= 0:
                            hist_chunk_id = all_chunks[h_idx].get("chunk_id")
                            if not isinstance(hist_chunk_id, str) or not CHUNK_ID_RE.match(hist_chunk_id):
                                logger.warning("worker: skipping chunk history with invalid id: %r", hist_chunk_id)
                                continue
                            if hist_chunk_id:
                                hist_path = Path("data/jobs/sessions") / session_id / f"chunk_{hist_chunk_id}.json"
                                if hist_path.exists():
                                    with open(hist_path, "r", encoding="utf-8") as hf:
                                        hist_data = json.load(hf)
                                        if hist_data.get("arabic_text"):
                                            history_chunks.append(hist_data)
    except Exception as e:
        logger.warning(f"Failed to load sliding window history for chunk {chunk_id}: {e}")
    
    retry_prompt = None
    is_phonetic_stretched = False
    phonetic_stretched_word = None
    
    if remaster_only:
        arabic_text = chunk.get("arabic_text", "")
        if not os.path.exists(final_tts_wav):
            return {"chunk_id": chunk_id, "status": "failed", "error": "No TTS file to remaster."}
    else:
        arabic_text = ""
        dynamic_min_words = None
        dynamic_max_words = None
        dynamic_f_pacing = None
        
        while retries <= max_retries:
            kurdish_text = chunk.get("kurdish_raw", "")
            source_word_count = len(kurdish_text.split())
            
            is_micro = chunk.get("is_micro", chunk.get("is_short", False))
            if source_word_count <= 2:
                is_micro = True
            
            phonetic_stretched_word = None
            if source_word_count == 1 and video_slot_duration >= 0.8:
                phonetic_stretched_word = kurdish_text.strip()
            
            is_phonetic_stretched = phonetic_stretched_word is not None
            
            # 1. Translate
            import re
            has_madd_multiplier = bool(re.search(r'(ا{3,}|و{3,}|ي{3,}|ى{3,})', chunk.get("arabic_text", "")))
            
            # If phonetic stretching is needed but the current text lacks Madd multipliers, force Gemini to handle it even if bypassed.
            force_gemini_stretch = is_phonetic_stretched and not has_madd_multiplier
            
            if bypass_initial_translation and retries == 0 and chunk.get("arabic_text") and not force_gemini_stretch:
                arabic_text = chunk["arabic_text"]
                logger.info(f"[PHYSICS] Bypassing initial Gemini translation, using manual text: {arabic_text}")
                trace_step(session_id, "TRANSLATE", chunk_id=chunk_id, status="SKIP",
                           note="bypass_initial_translation=True — using existing arabic_text", retry=retries)
            else:
                trace_step(session_id, "TRANSLATE", chunk_id=chunk_id, status="START",
                           note="translate_single_chunk_structured", retry=retries,
                           bypass_was=bypass_initial_translation)
                result = await translate_single_chunk_structured(
                    text=chunk.get("kurdish_raw", ""),
                    speech_duration=video_slot_duration,
                    padding_debt_ms=padding_debt_ms,
                    history=history_chunks,
                    retry_prompt=retry_prompt,
                    is_micro=is_micro,
                    wps=current_wps,
                    current_arabic_text=arabic_text if retries > 0 else chunk.get("arabic_text", ""),
                    phonetic_stretched_word=phonetic_stretched_word,
                    entity=session_state_dict.get("entity"),
                    category_id=session_state_dict.get("category_id"),
                    session_id=session_id
                )
                trace_step(session_id, "TRANSLATE", chunk_id=chunk_id, status="OK",
                           note="translate_single_chunk_structured done", retry=retries)
                
                new_text = result.get("arabic_text", "")
                if new_text:
                    arabic_text = new_text
            
            if not arabic_text:
                arabic_text = chunk.get("arabic_text", "")
                chunk["error"] = "Arabic text empty after translation"
                retries += 1
                await asyncio.sleep(2)
                continue
                
            # Safety Fallback: If phonetic stretch was requested but the final Arabic text lacks Madd multipliers,
            # cancel the bypass and fall back to FFmpeg mechanical stretching.
            if is_phonetic_stretched:
                has_madd_after = bool(re.search(r'(ا{3,}|و{3,}|ي{3,}|ى{3,})', arabic_text))
                if not has_madd_after:
                    logger.warning(f"[PHYSICS] Gemini failed to output multiplied Madd letters for '{arabic_text}'. Falling back to FFmpeg Atempo stretch.")
                    is_phonetic_stretched = False
                
            # Backend Enforcement Verification
            import re
            import math
            target_words = 0
            if dynamic_min_words is not None:
                min_words = dynamic_min_words
                max_words = dynamic_max_words
                f_pacing = dynamic_f_pacing
            else:
                if source_word_count <= 2:
                    min_words = 1
                    max_words = source_word_count
                    f_pacing = 1.0
                else:
                    # Reset to a pure 1:1 baseline ratio. 
                    # Previous equations were corrupted by the old speed pacing bug.
                    # The physics engine will dynamically add/delete words if this 1:1 guess is wrong.
                    ratio = 1.0
                    target_words = source_word_count * ratio
                    
                    # Strict boundary constraint (Target and Target+1)
                    min_words = max(1, math.floor(target_words))
                    max_words = min_words + 1
                    
                    # Lock initial TTS pacing to 1.0
                    f_pacing = 1.0
            
            clean_arabic = re.sub(r'[^\w\s\u0600-\u06FF]', '', arabic_text)
            actual_word_count = len(clean_arabic.split())
            
            # We no longer strictly reject based on word count alone!
            # As requested by the user, we will pass the text to Fish Audio 
            # and let the actual acoustic duration decide if it needs to be expanded or deleted.
                
            if translate_only:
                chunk["arabic_text"] = arabic_text
                chunk["status"] = "approved"
                # Fall through to the save logic below instead of breaking out and missing it
                break
                
            # 2. TTS
            lib_id, ref_audio = route_voice(chunk, session_state_dict)
            logger.info(f"[TTS] Chunk {chunk_id} routing result: lib_id={lib_id}, ref_audio={ref_audio}")
            success, err_msg = await generate_tts(
                text=arabic_text,
                reference_audio_path=ref_audio or "",
                output_wav=final_tts_wav,
                is_padded=chunk.get("padded", False),
                speech_duration=video_slot_duration,
                speed=f_pacing
            )
            
            if not success:
                logger.error(f"[TTS] generate_tts failed for chunk {chunk_id}: {err_msg}")
                chunk["tts_error"] = err_msg
                break
                
            try:
                from pydub import AudioSegment
                from pydub.silence import detect_nonsilent
                audio_tts = AudioSegment.from_file(final_tts_wav)
                nonsilent_ranges = detect_nonsilent(audio_tts, min_silence_len=50, silence_thresh=-40.0)
                if nonsilent_ranges:
                    end_idx = min(len(audio_tts), nonsilent_ranges[-1][1] + 50)
                    if end_idx < len(audio_tts):
                        audio_tts[:end_idx].export(final_tts_wav, format="wav")
                        logger.info(f"[TTS] Trimmed {len(audio_tts) - end_idx}ms of trailing silence from Fish Speech output.")
            except Exception as e:
                logger.warning(f"[TTS] Failed to trim trailing silence for chunk {chunk_id}: {e}")
                
            # 3. Post-TTS Measurement & Feedback Loop
            from app.services.vcta.tts_engine import _get_audio_duration
            tts_duration = await _get_audio_duration(final_tts_wav)
            
            if tts_duration > 0:
                scale = tts_duration / max(0.1, video_slot_duration)
                
                if scale < 0.95 or scale > 1.15:
                    logger.warning(f"[PHYSICS] Post-TTS validation failed! Scale {scale:.2f} is out of bounds [0.95, 1.15]. Bouncing back to Gemini.")
                    
                    if scale < 0.95:
                        # Asymmetric 1.10x expansion multiplier to provide safe speedup headroom
                        new_target = actual_word_count * (1.10 / scale)
                        dynamic_min_words = max(1, math.ceil(new_target))
                        dynamic_max_words = dynamic_min_words + 1
                        
                        # Lock pacing to 1.0 so we solely rely on Gemini's word count
                        dynamic_f_pacing = 1.0
                        
                        deficit = max(1, dynamic_min_words - actual_word_count)
                        retry_prompt = f"CRITICAL CORRECTION: The generated audio was too short. You MUST ADD EXACTLY {deficit} words to your translation to hit the physical video slot. Expand naturally, do not put filler at the start."
                    else:
                        new_target = actual_word_count * (1.0 / scale)
                        dynamic_max_words = max(1, math.ceil(new_target))
                        dynamic_min_words = max(1, dynamic_max_words - 1)
                        
                        # Lock pacing to 1.0 so we solely rely on Gemini's word count
                        dynamic_f_pacing = 1.0
                        
                        excess = max(1, actual_word_count - dynamic_max_words)
                        retry_prompt = f"CRITICAL CORRECTION: The generated audio was too long. You MUST DELETE EXACTLY {excess} words from your translation to hit the physical video slot. Strip unnecessary adjectives and filler."
                    
                    if retries >= max_retries:
                        logger.warning(f"[PHYSICS] Max retries reached. Forcing audio clamp for chunk {chunk_id}.")
                        trace_step(session_id, "PHYSICS_RETRY", chunk_id=chunk_id, status="FAIL",
                                   note="max_retries reached, clamping audio", retries=retries)
                        is_zone_c = True
                        chunk["arabic_text"] = arabic_text
                        chunk["f_pacing"] = f_pacing
                        break
                    else:
                        trace_step(session_id, "PHYSICS_RETRY", chunk_id=chunk_id, status="RETRY",
                                   note=f"scale out of bounds — retry {retries+1}", scale=round(scale, 3))
                        retries += 1
                        # We must bypass initial bypass check on subsequent retries
                        bypass_initial_translation = False
                        continue
                else:
                    logger.info(f"[PHYSICS] Post-TTS validation passed! Scale {scale:.2f} is perfectly within [0.95, 1.15].")
            else:
                logger.warning("[PHYSICS] TTS duration measurement failed. Proceeding blindly.")

            # Audio passed physics check or max retries reached
            chunk["arabic_text"] = arabic_text
            chunk["f_pacing"] = f_pacing
            break
        
    # Write translation texts if successful
    if arabic_text:
        dir_translation = Path("data/jobs/sessions") / session_id / "4-translation"
        dir_side = Path("data/jobs/sessions") / session_id / "5-side_by_side"
        dir_translation.mkdir(parents=True, exist_ok=True)
        dir_side.mkdir(parents=True, exist_ok=True)
        
        chunk_kurdish = chunk.get("kurdish_raw", "")
        with open(dir_translation / f"chunk_{idx}_translation.txt", "w", encoding="utf-8") as f:
            f.write(arabic_text)
        with open(dir_side / f"chunk_{idx}_side_by_side.txt", "w", encoding="utf-8") as f:
            f.write(f"KURDISH:\n{chunk_kurdish}\n\nARABIC:\n{arabic_text}")
            
    # 5. FFmpeg Atempo Assembly (Stretches the raw speech)
    if not translate_only:
        if not os.path.exists(final_tts_wav):
            err_msg = chunk.get("tts_error") or chunk.get("error") or "TTS generation failed."
            logger.error(f"[ASSEMBLY] final_tts_wav missing for chunk {chunk_id} at {final_tts_wav}. Error: {err_msg}")
            
            # Write to terminal log
            session_dir = Path("data/jobs/sessions") / session_id
            log_path = session_dir / "terminal.log"
            if log_path.parent.exists():
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(f"[ERROR] Chunk {chunk_id} TTS failed: {err_msg}\n")
                    
            return {"chunk_id": chunk_id, "status": "failed", "error": err_msg}
            
        try:
            target_active_duration = max(0.1, video_slot_duration)
            
            if is_phonetic_stretched:
                logger.info(f"PHONETIC BYPASS: Skipping FFmpeg Atempo for chunk {chunk_id}, utilizing Fish Audio natural stretch.")
                assembled_wav = str(assembled_dir / f"chunk_{chunk_id}_assembled.wav")
                import shutil
                shutil.copy(final_tts_wav, assembled_wav)
            else:
                from scripts.audio_assembly import process_chunk_assembly
                from pydub import AudioSegment
                from pydub.silence import detect_nonsilent
                
                chunk, assembled_wav, _, _ = await process_chunk_assembly(
                    chunk=chunk,
                    tts_dir=str(tts_dir),
                    output_dir=str(assembled_dir),
                    rolling_cps=13.5, 
                    padding_debt_ms=0.0,
                    target_active_duration=target_active_duration
                )
        except Exception as e:
            logger.error(f"Assembly failed: {e}")
            return {"chunk_id": chunk_id, "status": "failed", "error": str(e)}

        # 6. AUTO-MASTERING & TIMELINE RESTORATION (Pads onset & mixes)
        if os.path.exists(assembled_wav):
            from app.services.vcta.audio_pipeline import master_and_align_chunk
            mastered_dir = Path("data/jobs/sessions") / session_id / "mastered_chunks"
            mastered_dir.mkdir(parents=True, exist_ok=True)
            mastered_wav = str(mastered_dir / f"chunk_{idx}_mastered.wav")
            
            try:
                metadata = master_and_align_chunk(
                    original_chunk_path=chunk.get("audio_file"),
                    tts_chunk_path=assembled_wav,  # Pass the stretched speech
                    output_path=mastered_wav,
                    vocal_stem_path=chunk.get("vocal_file"),
                    leading_silence_threshold_dbfs=-40.0,
                    silence_detection_chunk_ms=1,
                    presence_boost_db=1.5,
                    export_format="wav"
                )
                chunk["mastering_metadata"] = metadata
                logger.info(f"[MASTERING] Chunk {chunk_id} mastered successfully.")
            except Exception as e:
                logger.error(f"[MASTERING] Failed to master chunk {chunk_id}: {e}")
                # Fallback: just use the stretched TTS if mastering fails
                import shutil
                shutil.copy(assembled_wav, mastered_wav)

            # Copy the TTS file to 6-arabic_audio_chunks (for legacy/UI)
            import shutil
            shutil.copy(mastered_wav, str(dir_arabic / f"chunk_{idx}_arabic.wav"))
            chunk["tts_url"] = f"/static/outputs/raw_tts_{chunk_id}.wav"
            chunk["tts_file"] = mastered_wav
            chunk["status"] = "approved"

    # Circuit Breaker Tracking
    if not translate_only:
        try:
            pipe = redis_client.pipeline()
            pipe.incr(processed_key)
            if is_zone_c:
                pipe.incr(zone_c_key)
            results = pipe.execute()
            new_processed = results[0]
            new_zone_c = results[1] if is_zone_c else int(redis_client.get(zone_c_key) or 0)
            
            if new_processed > 20 and (new_zone_c / new_processed) > 0.15:
                # Trip the breaker
                logger.error(f"[CIRCUIT BREAKER] Tripped! {new_zone_c} Zone C failures out of {new_processed} chunks.")
                await update_job_status(session_id, "requires_wps_recalibration", error="This video has highly complex pacing that our system cannot currently process. Please try a different video.")
                celery.control.purge()
                raise CriticalHaltException("Financial API drain prevented.")
        except Exception as e:
            logger.warning(f"Could not update Redis Circuit Breaker (Redis likely offline): {e}")

    try:
        chunk_json_path = Path("data/jobs/sessions") / session_id / f"chunk_{chunk_id}.json"
        with open(chunk_json_path, "w", encoding="utf-8") as f:
            json.dump(chunk, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Failed to save final chunk state: {e}")

    return chunk

async def _async_process_tts_only(chunk: dict, session_id: str, session_state_dict: dict):
    """
    Manually run just the TTS portion of the Physics Engine (Step 6 bypass).
    """
    chunk_id = chunk["chunk_id"]
    arabic_text = chunk.get("arabic_text", "")
    video_slot_duration = chunk.get("speech_duration", chunk.get("duration_sec", 0.0))
    
    if not arabic_text:
        return {"chunk_id": chunk_id, "status": "skipped", "error": "No translated text."}
        
    dir_arabic = Path("data/jobs/sessions") / session_id / "6-arabic_audio_chunks"
    dir_arabic.mkdir(parents=True, exist_ok=True)
    tts_dir = Path("data/jobs/sessions") / session_id / "tts"
    tts_dir.mkdir(parents=True, exist_ok=True)
    
    final_tts_wav = str(tts_dir / f"raw_tts_{chunk_id}.wav")
    
    try:
        from app.services.vcta.voice_router import route_voice
        from app.services.vcta.tts_engine import generate_tts
        
        lib_id, ref_audio = route_voice(chunk, session_state_dict)
        success = await generate_tts(
            text=arabic_text,
            reference_audio_path=ref_audio or "",
            output_wav=final_tts_wav,
            is_padded=chunk.get("padded", False),
            speech_duration=video_slot_duration
        )
        
        if success and os.path.exists(final_tts_wav):
            # Try to get idx from state.json
            idx = 1
            try:
                import json
                state_path = Path("data/jobs/sessions") / session_id / "state.json"
                if state_path.exists():
                    with open(state_path, "r", encoding="utf-8") as f:
                        state_data = json.load(f)
                        all_chunks = state_data.get("chunks", [])
                        for i, c in enumerate(all_chunks):
                            if c.get("chunk_id") == chunk_id:
                                idx = i + 1
                                break
            except:
                pass
                
            shutil.copy(final_tts_wav, str(dir_arabic / f"chunk_{idx}_arabic.wav"))
            chunk["tts_url"] = f"/static/outputs/raw_tts_{chunk_id}.wav"
            chunk["tts_file"] = final_tts_wav
            chunk["status"] = "tts_done"
        else:
            chunk["status"] = "failed"
            chunk["error"] = "TTS Generation failed."
            
    except Exception as e:
        logger.error(f"TTS Only dispatch failed: {e}")
        chunk["status"] = "failed"
        chunk["error"] = str(e)
        
    try:
        import json
        chunk_json_path = Path("data/jobs/sessions") / session_id / f"chunk_{chunk_id}.json"
        with open(chunk_json_path, "w", encoding="utf-8") as f:
            json.dump(chunk, f, ensure_ascii=False, indent=2)
    except:
        pass
        
    return chunk

@celery.task
def assemble_video_task(results, session_id: str, video_path: str, bg_wav: str):
    """
    Service C: The Assembler
    Triggered via Chord when all process_chunk_tasks complete.
    """
    with session_log_context(session_id):
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
        return loop.run_until_complete(_async_assemble_video(results, session_id, video_path, bg_wav))

async def _async_assemble_video(results, session_id: str, video_path: str, bg_wav: str, reference_profile: dict = None):
    logger.info(f"[ASSEMBLER] All chunks completed for session {session_id}. Starting mix.")
    
    # Check if breaker tripped
    job = await get_job(session_id)
    if job and job.get("status") == "requires_wps_recalibration":
        logger.warning("Job requires WPS recalibration. Skipping final assembly.")
        return False
        
    # Log all results for debugging
    failed_chunks = [c for c in results if isinstance(c, dict) and c.get("status") in ("failed", "skipped")]
    for c in failed_chunks:
        logger.error(f"[ASSEMBLY_CHECK] Chunk {c.get('chunk_id')} failed/skipped with error: {c.get('error', 'Unknown')}")
        
    # Valid chunks
    valid_chunks = [c for c in results if isinstance(c, dict) and c.get("status") in ("approved", "tts_done", "pending")]
    
    if not valid_chunks and failed_chunks:
        errors = [c.get("error") for c in failed_chunks if c.get("error")]
        unique_errors = list(set(errors))
        error_msg = f"All chunks failed processing. Errors: {', '.join(unique_errors)}"
        logger.error(f"[ASSEMBLY] {error_msg}")
        session_dir = Path("data/jobs/sessions") / session_id
        log_path = session_dir / "terminal.log"
        if log_path.parent.exists():
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"[ERROR] Stage 5 Assembly Failed: {error_msg}\n")
        await update_job_status(session_id, "failed", error=error_msg)
        raise RuntimeError(error_msg)
    
    assembled_dir = Path("data/jobs/sessions") / session_id / "assembled"
    final_audio = str(assembled_dir / "final_dub.wav")
    final_video = str(assembled_dir / "final_dubbed.mp4")
    
    # Run assembler
    try:
        session_dir = Path("data/jobs/sessions") / session_id
        
        # Notify the frontend UI that FFmpeg mixing has started so the user doesn't restart the server
        log_path = session_dir / "terminal.log"
        if log_path.parent.exists():
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"[INFO] Stage 5: Assembling {len(valid_chunks)} clips against silent master. This may take 1-3 minutes...\n")
                f.write(f"[INFO] Concatenating Arabic vocals into single track...\n")
        
        final_wav = await assemble_final_video(
            chunks=valid_chunks,
            background_wav=bg_wav,
            video_path=video_path,
            work_dir=str(session_dir),
            reference_profile=reference_profile
        )
        
        await update_job_status(session_id, "completed", output_path=final_video)
        logger.info(f"Video {session_id} dubbing completed successfully!")
        return True
    except Exception as e:
        logger.error(f"Final assembly failed: {e}")
        await update_job_status(session_id, "failed", error=str(e))
        raise e
