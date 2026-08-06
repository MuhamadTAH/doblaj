import os
import uuid
import json
import shutil
import logging
import asyncio
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends, Request
from app.auth.clerk_auth import require_user, AuthenticatedUser
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List, Optional

from app.core.session_logger import session_log_context

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/entities")
async def get_entities(user: AuthenticatedUser = Depends(require_user)):
    from app.core.database_convex import _get_service_role_client
    import asyncio
    try:
        client = _get_service_role_client()
        def _do():
            return client.query("dictionaries:listCategoriesInternal", {}) or []
        categories = await asyncio.to_thread(_do)
        return {"entities": categories}
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to fetch entities: {e}")
        return {"entities": []}

BASE_DIR = Path("data/jobs/sessions")

def _get_session_dir(session_id: str) -> Path:
    d = BASE_DIR / session_id
    d.mkdir(parents=True, exist_ok=True)
    return d

def _read_state(session_id: str) -> dict:
    state_file = _get_session_dir(session_id) / "state.json"
    if state_file.exists():
        with open(state_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def _write_state(session_id: str, state: dict):
    state_file = _get_session_dir(session_id) / "state.json"
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def _clear_individual_chunk_files(session_dir: Path):
    """Deletes stale chunk_*.json files to prevent them from corrupting the state on resume."""
    import glob
    for cf in glob.glob(str(session_dir / "chunk_*.json")):
        try:
            os.remove(cf)
        except Exception:
            pass

def _log(session_id: str, message: str, level: str = "INFO"):
    """Write to both the global logger and a session-specific log file for easy polling."""
    # Write to global logger
    msg = f"[JOB {session_id}] {message}"
    if level == "ERROR":
        logger.error(msg)
    elif level == "WARNING":
        logger.warning(msg)
    else:
        logger.info(msg)
        
    # Write to session log for the UI terminal
    log_file = _get_session_dir(session_id) / "terminal.log"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"[{level}] {message}\n")

@router.get("/logs/{session_id}")
async def get_logs(session_id: str, user: AuthenticatedUser = Depends(require_user)):
    state = _read_state(session_id)
    if not state or state.get("workspace_id") != user.workspace_id:
        # ponytail: 404 (not 403) so we don't leak session existence to
        # other workspaces. Same shape as Option B in
        # handoffs/dubbing-audit-fixes-2026-07-15.md Fix 1.
        return JSONResponse({"logs": []})
    log_file = _get_session_dir(session_id) / "terminal.log"
    if not log_file.exists():
        return JSONResponse({"logs": []})
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        # Return last 100 lines
        return JSONResponse({"logs": [line.strip() for line in lines[-100:]]})
    except Exception as e:
        return JSONResponse({"logs": [f"[ERROR] Failed to read logs: {e}"]})

@router.get("/state/{session_id}")
async def get_state(session_id: str, user: AuthenticatedUser = Depends(require_user)):
    state = _read_state(session_id)
    if not state or state.get("workspace_id") != user.workspace_id:
        raise HTTPException(status_code=404, detail="State not found")
        
    # Thread Safety Fix: Merge individual chunk files back into state for the UI
    import glob
    session_dir = _get_session_dir(session_id)
    chunk_files = glob.glob(str(session_dir / "chunk_*.json"))
    chunk_map = {}
    for cf in chunk_files:
        try:
            with open(cf, "r", encoding="utf-8") as f:
                cdata = json.load(f)
                if "chunk_id" in cdata:
                    chunk_map[str(cdata["chunk_id"])] = cdata
        except:
            pass
            
    if chunk_map and "chunks" in state:
        for i, c in enumerate(state["chunks"]):
            cid = str(c.get("chunk_id"))
            if cid in chunk_map:
                state["chunks"][i].update(chunk_map[cid])
                
    return state

SAVED_SESSIONS_FILE = Path("data/jobs/manual/saved_sessions.json")

def _get_saved_sessions():
    if not SAVED_SESSIONS_FILE.exists():
        return {}
    try:
        with open(SAVED_SESSIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def _save_saved_sessions(data):
    SAVED_SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SAVED_SESSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

@router.post("/save-session")
async def save_session(
    filename: str = Form(...),
    filesize: int = Form(...),
    session_id: str = Form(...),
    user: AuthenticatedUser = Depends(require_user)
):
    key = f"{filename}_{filesize}"
    sessions = _get_saved_sessions()
    sessions[key] = session_id
    _save_saved_sessions(sessions)
    _log(session_id, f"Session bookmarked for file: {filename}")
    return {"status": "success"}

# Step 1: Upload
@router.post("/step1-upload")
async def step1_upload(
    file: UploadFile = File(...), 
    entity: str = Form(""),
    category_id: str = Form("automotive"),
    user: AuthenticatedUser = Depends(require_user)
):
    # Pird: bounded read. See handoffs/dubbing-security-pass3-fixes.md Fix 4.
    _MAX = 1024 * 1024 * 1024  # 1 GB
    _chunks = []
    _total = 0
    while True:
        _c = await file.read(64 * 1024)
        if not _c:
            break
        _total += len(_c)
        if _total > _MAX:
            raise HTTPException(status_code=413, detail=f"Upload exceeds {_MAX} bytes")
        _chunks.append(_c)
    content = b"".join(_chunks)
    filesize = len(content)
    key = f"{file.filename}_{filesize}"
    
    sessions = _get_saved_sessions()
    if key in sessions:
        restored_session = sessions[key]
        try:
            state = _read_state(restored_session)
            state["restored"] = True
            state["entity"] = entity
            state["category_id"] = category_id
            _write_state(restored_session, state)
            _log(restored_session, f"Resuming previous session from bookmark!")
            return state
        except:
            pass # State file might be deleted, fallback to new session
            
    jobs_base = Path("data/jobs/sessions")
    jobs_base.mkdir(parents=True, exist_ok=True)
    existing_folders = []
    for d in jobs_base.iterdir():
        if d.is_dir() and d.name.isdigit():
            existing_folders.append(int(d.name))
    next_id = max(existing_folders) + 1 if existing_folders else 1
    session_id = str(next_id)
    
    _log(session_id, "Starting Step 1: Upload & Audio Extraction")
    
    session_dir = _get_session_dir(session_id)
    
    # 8-Folder Initialization
    dir_sep = session_dir / "1-separation"
    dir_chunks = session_dir / "2-chunks"
    dir_transcription = session_dir / "3-transcription"
    dir_translation = session_dir / "4-translation"
    dir_side = session_dir / "5-side_by_side"
    dir_arabic = session_dir / "6-arabic_audio_chunks"
    dir_full_video = session_dir / "7-full_arabic_video_no_noise"
    dir_final = session_dir / "8-final_dubbed_video"
    
    for d in [dir_sep, dir_chunks, dir_transcription, dir_translation, dir_side, dir_arabic, dir_full_video, dir_final]:
        d.mkdir(parents=True, exist_ok=True)
    
    upload_path = dir_sep / "Video_Upload_Original.mp4"
    video_path = dir_sep / "Video_0_Master_095x.mp4"
    
    _log(session_id, f"Saving original video file to {upload_path}")
    with open(upload_path, "wb") as f:
        f.write(content)

    # 1. Probing duration
    try:
        import ffmpeg
        import math
        probe = ffmpeg.probe(str(upload_path))
        format_info = probe.get("format", {})
        duration = float(format_info.get("duration", 0.0))
    except Exception as e:
        duration = 0.0

    if duration <= 0:
        if upload_path.exists():
            upload_path.unlink()
        raise HTTPException(status_code=400, detail="We couldn't read the audio track. Ensure your video file isn't corrupted and try again.")

    duration_minutes = math.ceil(duration / 60.0)

    # 2. Check balance
    from app.core import db as database
    try:
        user_client = database.get_user_client(user.access_token)
        remaining_minutes = await database.get_workspace_minutes(user_client, workspace_id=user.workspace_id)
    except Exception as e:
        if upload_path.exists():
            upload_path.unlink()
        logger.exception("Failed to query workspace minutes balance")
        raise HTTPException(status_code=500, detail="Failed to verify balance")

    if remaining_minutes < duration_minutes:
        if upload_path.exists():
            upload_path.unlink()
        raise HTTPException(
            status_code=402,
            detail=f"You do not have enough minutes. This video requires {duration_minutes} minutes, but you only have {remaining_minutes} minutes remaining. Please visit the pricing page to add more minutes."
        )

    # 3. Deduct minutes from balance
    try:
        await database.deduct_workspace_minutes(user_client, workspace_id=user.workspace_id, minutes=duration_minutes)
        logger.info(f"Reserved {duration_minutes} minutes from workspace {user.workspace_id} (remaining: {remaining_minutes - duration_minutes})")
    except Exception as e:
        if upload_path.exists():
            upload_path.unlink()
        logger.exception("Failed to deduct workspace minutes balance")
        raise HTTPException(status_code=500, detail="Failed to process billing reservation")
        
    # Validation: Check if the video has an audio track
    import subprocess
    try:
        probe_cmd = [
            "ffprobe", "-v", "error", "-select_streams", "a",
            "-show_entries", "stream=index", "-of", "csv=p=0", str(upload_path)
        ]
        probe_res = subprocess.run(probe_cmd, capture_output=True, text=True)
        if not probe_res.stdout.strip():
            _log(session_id, "No audio track found in the uploaded video.", "ERROR")
            raise HTTPException(status_code=400, detail="The uploaded video has no audio track. Please upload a video with spoken audio.")
    except HTTPException:
        raise
    except Exception as e:
        _log(session_id, f"Failed to probe audio tracks: {e}", "WARNING")
        

    if not video_path.exists():
        _log(session_id, "Applying Phase 0: Global Pre-Stretch to 0.95x speed (Compute Tax)...")
        try:
            import subprocess
            cmd = [
                "ffmpeg", "-y", "-i", str(upload_path),
                "-filter_complex", "[0:v]setpts=1.0526*PTS[v];[0:a]atempo=0.95[a]",
                "-map", "[v]", "-map", "[a]",
                "-c:v", "libx264", "-crf", "18", "-preset", "fast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-ar", "44100", "-b:a", "192k",
                str(video_path)
            ]
            await asyncio.to_thread(
                subprocess.run, cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True
            )
            _log(session_id, "Phase 0 Global Pre-Stretch complete!")
        except Exception as e:
            _log(session_id, f"Phase 0 Pre-Stretch failed: {e}. Falling back to original video.", "ERROR")
            shutil.copy(str(upload_path), str(video_path))
    else:
        _log(session_id, "Phase 0 Master already exists. Skipping re-encode (Idempotent).")
        
    # Extract audio from the NEW stretched master
    _log(session_id, "Extracting full audio from 0.95x master video...")
    audio_raw = dir_sep / "Audio_1_Original_Kurdish_Noise.wav"
    from app.services.video.transcriber import extract_audio
    success, _ = await extract_audio(str(video_path), str(audio_raw))
    if not success:
        _log(session_id, "Audio extraction failed!", "ERROR")
        raise HTTPException(status_code=500, detail="Extraction failed")
        
    _log(session_id, "Audio extraction complete.")
    
    # Copy stretched video to static so UI can play it
    static_video = Path(f"static/outputs/manual_{session_id}.mp4")
    static_video.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(str(video_path), str(static_video))
    
    state = {
        "session_id": session_id,
        "video_path": str(video_path),
        "video_url": f"/static/outputs/manual_{session_id}.mp4",
        "audio_raw": str(audio_raw),
        "entity": entity,
        "category_id": category_id,
        "workspace_id": user.workspace_id,
        "owner_user_id": user.user_id,
    }
    _write_state(session_id, state)
    
    return state

# Step 2: Separate
@router.post("/step2-separate")
async def step2_separate(session_id: str = Form(...), user: AuthenticatedUser = Depends(require_user)): 
    _log(session_id, "Starting Step 2: Audio Separation (Vocals vs Background)")
    state = _read_state(session_id)
    from app.services.vcta import isolation
    import asyncio
    _log(session_id, "Running VCTA Vocal Isolation v3.0... this may take a moment.")
    
    try:
        dir_sep = _get_session_dir(session_id) / "1-separation"
        iso_results = await asyncio.to_thread(isolation.run_vcta_pipeline, state["audio_raw"], str(dir_sep))
        
        # Safe rename helper to bypass WinError 32 locks on retries
        async def safe_replace(src_path, dst_path):
            import shutil
            import time
            for attempt in range(10):
                try:
                    await asyncio.to_thread(shutil.copy2, src_path, dst_path)
                    try:
                        await asyncio.to_thread(os.remove, src_path)
                    except OSError:
                        pass
                    return str(dst_path)
                except OSError as e:
                    await asyncio.sleep(1.0)
            
            # Final fallback if it's permanently locked
            fallback = str(dst_path).replace(".wav", f"_{int(time.time())}.wav")
            await asyncio.to_thread(shutil.copy2, src_path, fallback)
            try:
                await asyncio.to_thread(os.remove, src_path)
            except OSError:
                pass
            return fallback

        voc_wav = await safe_replace(iso_results['paths']['fish_audio'], dir_sep / "Audio_2_Vocal_Only_Kurdish.wav")
        bg_wav = await safe_replace(iso_results['paths']['instrumental'], dir_sep / "Audio_3_Noise_Only.wav")
        pyannote_wav = iso_results['paths']['pyannote']
        
        video_path = state["video_path"]
        
        # Generate the two remaining Video Files using FFmpeg
        import subprocess
        _log(session_id, "Generating Separated Video Files")
        video_vocal = dir_sep / "Video_2_Vocal_Only_Kurdish.mp4"
        await asyncio.to_thread(
            subprocess.run,
            [
                "ffmpeg", "-y", "-i", str(video_path), "-i", voc_wav,
                "-c:v", "copy", "-c:a", "aac", "-map", "0:v:0", "-map", "1:a:0",
                str(video_vocal)
            ],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        
        video_noise = dir_sep / "Video_3_Noise_Only.mp4"
        await asyncio.to_thread(
            subprocess.run,
            [
                "ffmpeg", "-y", "-i", str(video_path), "-i", bg_wav,
                "-c:v", "copy", "-c:a", "aac", "-map", "0:v:0", "-map", "1:a:0",
                str(video_noise)
            ],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        
        raw_rof = iso_results.get('raw_roformer')
        raw_dem = iso_results.get('raw_demucs')
        
        state["pyannote_wav"] = pyannote_wav
        
        static_voc = Path(f"static/outputs/voc_{session_id}.wav")
        static_bg = Path(f"static/outputs/bg_{session_id}.wav")
        shutil.copy(voc_wav, str(static_voc))
        
        if raw_rof and os.path.exists(raw_rof):
            static_rof = Path(f"static/outputs/raw_roformer_{session_id}.wav")
            shutil.copy(raw_rof, str(static_rof))
            state["raw_roformer_url"] = f"/static/outputs/raw_roformer_{session_id}.wav"
            
        if raw_dem and os.path.exists(raw_dem):
            static_dem = Path(f"static/outputs/raw_demucs_{session_id}.wav")
            shutil.copy(raw_dem, str(static_dem))
            state["raw_demucs_url"] = f"/static/outputs/raw_demucs_{session_id}.wav"

        if os.path.exists(bg_wav):
            shutil.copy(bg_wav, str(static_bg))
            state["bg_url"] = f"/static/outputs/bg_{session_id}.wav"
            state["bg_wav"] = str(bg_wav)
        else:
            _log(session_id, "No background audio detected. Generating silence.", "WARNING")
            
        state["voc_url"] = f"/static/outputs/voc_{session_id}.wav"
        state["voc_wav"] = voc_wav
        _write_state(session_id, state)
        _log(session_id, "Stem separation complete!")
        return state
    except Exception as e:
        _log(session_id, f"Separation failed: {e}", "ERROR")
        raise HTTPException(status_code=500, detail="Internal server error")

# Step 3: Chunk
@router.post("/step3-chunk")
async def step3_chunk(session_id: str = Form(...), user: AuthenticatedUser = Depends(require_user)): 
    _log(session_id, "Starting Step 3: Pyannote Diarization & Slicing")
    state = _read_state(session_id)
    from app.services.vcta import chunker
    import subprocess
    import uuid
    import os
    
    try:
        diarize_target = state.get("pyannote_wav", state["voc_wav"])
        final_chunks, purged_gaps = await chunker.run_diarization(diarize_target)
        if not final_chunks:
            _log(session_id, "No speech chunks found in vocals!", "ERROR")
            raise HTTPException(status_code=400, detail="No speech detected")
            
        # Stage 3.5: Secondary Speaker / Quran Verse Restoration
        _log(session_id, "Restoring secondary speakers and background verses to the noise track...")
        from app.services.vcta.restoration import restore_background_vocals
        restored_bg_wav = str(_get_session_dir(session_id) / "1-separation" / "Audio_3_Noise_Only_Restored.wav")
        muted_fish_wav = str(_get_session_dir(session_id) / "1-separation" / "Audio_2_Vocal_Only_Kurdish_Muted.wav")
        
        success = await asyncio.to_thread(
            restore_background_vocals,
            vocals_wav_path=state["voc_wav"],
            instrumental_wav_path=state["bg_wav"],
            output_bg_wav_path=restored_bg_wav,
            output_vocals_wav_path=muted_fish_wav,
            purged_turns=purged_gaps
        )
        if success and os.path.exists(restored_bg_wav):
            state["bg_wav"] = restored_bg_wav
            state["voc_wav"] = muted_fish_wav
            _write_state(session_id, state)
            _log(session_id, "Secondary audio restored successfully.")
            
        # Thread Safety: Use 2-chunks directory
        dir_chunks = _get_session_dir(session_id) / "2-chunks"
        dir_chunks.mkdir(parents=True, exist_ok=True)
        
        chunks = []
        for idx, c in enumerate(final_chunks, 1):
            duration = c["end"] - c["start"]
            chunk_id = f"chunk_{uuid.uuid4().hex[:8]}"
            
            # The Voice Cloning Corruption Fix (All chunks < 1.5s are explicitly blacklisted)
            is_short = bool(duration < 1.5)
            
            file_path = str(dir_chunks / f"chunk_{idx}_audio.wav")
            vocal_file_path = str(dir_chunks / f"chunk_{idx}_vocal.wav")
            video_chunk_path = str(dir_chunks / f"chunk_{idx}_video.mp4")
            tmp_path = file_path + ".tmp"
            tmp_vocal_path = vocal_file_path + ".tmp"
            
            # Structural Overlap Padding (Now strictly uses the Zero-Gap Contiguous Boundaries)
            padded_start = max(0.0, c["start_time"])
            padded_end = c["end_time"]
            padded_duration = padded_end - padded_start
            
            # Atomic FFmpeg Slicing
            try:
                # Phase 2: Enforce Codec/Bandwidth (16kHz, mono, 16-bit PCM WAV)
                # 1. Slice Original Audio Mix
                process = await asyncio.to_thread(
                    subprocess.run,
                    [
                        "ffmpeg", "-y", "-i", state["audio_raw"], 
                        "-ss", str(padded_start), "-t", str(padded_duration), 
                        "-c:a", "pcm_s16le", "-ac", "1", "-ar", "16000", "-f", "wav", tmp_path
                    ], 
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
                )
                
                if process.returncode != 0:
                    raise Exception("We couldn't process this specific audio segment. Please refresh the page and try again.")
                await asyncio.to_thread(os.replace, tmp_path, file_path)
                
                # 2. Slice Vocal Stem (Enforce 16kHz, mono, 16-bit PCM)
                process_voc = await asyncio.to_thread(
                    subprocess.run,
                    [
                        "ffmpeg", "-y", "-i", state["voc_wav"], 
                        "-ss", str(padded_start), "-t", str(padded_duration), 
                        "-c:a", "pcm_s16le", "-ac", "1", "-ar", "16000", "-f", "wav", tmp_vocal_path
                    ], 
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
                )
                
                if process_voc.returncode != 0:
                    raise Exception("We couldn't process this specific audio segment. Please refresh the page and try again.")
                await asyncio.to_thread(os.replace, tmp_vocal_path, vocal_file_path)
                    
                # 3. Slice the video chunk
                await asyncio.to_thread(
                    subprocess.run,
                    [
                        "ffmpeg", "-y", "-i", state["video_path"], 
                        "-ss", str(padded_start), "-t", str(padded_duration), 
                        "-c", "copy", video_chunk_path
                    ], 
                    check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            except Exception as e:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                if os.path.exists(tmp_vocal_path):
                    os.unlink(tmp_vocal_path)
                raise Exception("We couldn't process this specific audio segment. Please refresh the page and try again.")
            
            # Unified JSON Schema
            c_dict = {
                "chunk_id": chunk_id,
                "audio_file": file_path,
                "vocal_file": vocal_file_path,
                "file_path": file_path,
                "is_short": is_short,
                
                # Legacy/UI keys (We set them to the contiguous boundaries so the UI and downstream pipeline stays synced)
                "start_time": c["start_time"],
                "end_time": c["end_time"],
                "duration_sec": c["total_duration"],
                
                # The contiguous boundaries (Critical for Speed Multiplier Trap in Step 5)
                "speech_duration": c["total_duration"],
                "total_duration": c["total_duration"],
                "contig_start": c["start_time"],
                "contig_end": c["end_time"],
                
                # Original boundaries (kept for reference or strict clipping)
                "vad_start": c.get("vad_start", c["start"]),
                "vad_end": c.get("vad_end", c["end"]),
                
                "speaker_id": c["speaker"],
                "speaker": c["speaker"],
                "audio_url": f"/static/outputs/{chunk_id}.wav",
                "kurdish_raw": "",
                "status": "pending"
            }
            chunks.append(c_dict)
            
        _log(session_id, f"Created {len(chunks)} audio chunks in {dir_chunks}.")
        
        # Copy to static for UI Preview
        for i, c in enumerate(chunks):
            static_chunk = Path(f"static/outputs/{c['chunk_id']}.wav")
            shutil.copy(c["vocal_file"], str(static_chunk))
            c["audio_url"] = f"/static/outputs/{c['chunk_id']}.wav"
            
        state["chunks"] = chunks
        _clear_individual_chunk_files(_get_session_dir(session_id))
        _write_state(session_id, state)
        _log(session_id, "Chunking complete!")
        return state
    except Exception as e:
        _log(session_id, f"Chunking failed: {e}", "ERROR")
        raise HTTPException(status_code=500, detail="Internal server error")

import zipfile
@router.post("/step3-upload-chunks")
async def step3_upload_chunks(file: UploadFile = File(...), session_id: Optional[str] = Form(None), user: AuthenticatedUser = Depends(require_user)): 
    if not session_id or session_id == "null":
        session_id = f"job_{uuid.uuid4().hex[:8]}"
        
    _log(session_id, f"Starting chunk ZIP upload...")
    
    session_dir = _get_session_dir(session_id)
    zip_path = session_dir / file.filename
    with open(zip_path, "wb") as f:
        # Pird: bounded read. See Fix 4.
        _MAX = 1024 * 1024 * 1024
        _total = 0
        while True:
            _c = await file.read(64 * 1024)
            if not _c:
                break
            _total += len(_c)
            if _total > _MAX:
                raise HTTPException(status_code=413, detail=f"Upload exceeds {_MAX} bytes")
            f.write(_c)
        
    _log(session_id, f"Extracting {file.filename}...")
    
    chunks_dir = session_dir / "uploaded_chunks"
    chunks_dir.mkdir(exist_ok=True)
    
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(chunks_dir)
    except Exception as e:
        _log(session_id, f"ZIP extraction failed: {e}", "ERROR")
        raise HTTPException(status_code=400, detail="Invalid ZIP file")
        
    wav_files = list(chunks_dir.glob("**/*.wav"))
    if not wav_files:
        _log(session_id, "No .wav files found in the uploaded ZIP!", "ERROR")
        raise HTTPException(status_code=400, detail="No .wav files found in ZIP")
        
    wav_files.sort()
    _log(session_id, f"Found {len(wav_files)} chunks. Processing...")
    
    from app.services.vcta.tts_engine import _get_audio_duration
    
    chunks = []
    current_time = 0.0
    for i, wav_path in enumerate(wav_files):
        dur = await _get_audio_duration(str(wav_path))
        
        standard_chunk_file = str(session_dir / f"chunk_{uuid.uuid4().hex}.wav")
        shutil.copy(str(wav_path), standard_chunk_file)
        
        static_chunk = Path(f"static/outputs/chunk_{session_id}_{i}.wav")
        static_chunk.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(standard_chunk_file, str(static_chunk))
        
        c_dict = {
            "chunk_id": Path(standard_chunk_file).stem.replace("chunk_", ""),
            "audio_file": standard_chunk_file,
            "duration_sec": dur,
            "speech_duration": dur,
            "start_time": current_time,
            "speaker": "SPEAKER_00",
            "audio_url": f"/static/outputs/chunk_{session_id}_{i}.wav",
            "kurdish_raw": "",
            "status": "pending"
        }
        chunks.append(c_dict)
        current_time += dur + 0.5
        
    state = _read_state(session_id)
    if not state:
        state = {"session_id": session_id}
    state["chunks"] = chunks
    _clear_individual_chunk_files(session_dir)
    _write_state(session_id, state)
    
    _log(session_id, "Chunk ZIP processing complete!")
    return state

# Step 4: Transcribe
@router.post("/step4-transcribe")
async def step4_transcribe(session_id: str = Form(...), user: AuthenticatedUser = Depends(require_user)): 
    _log(session_id, "Starting Step 4: Gemini 3 Flash Transcription")
    state = _read_state(session_id)
    
    from app.services.video import ai_transcription
    chunks = state.get("chunks", [])
    
    try:
        session_dir = _get_session_dir(session_id)
        
        # Clear out old chunk state files from previous runs to prevent UI cache pollution
        import glob
        import os
        for old_file in glob.glob(str(session_dir / "chunk_*.json")):
            try:
                os.remove(old_file)
            except:
                pass
                
        dir_trans = session_dir / "3-transcription"
        dir_trans.mkdir(parents=True, exist_ok=True)
        entity = state.get("entity", "")
        
        async def _process_batch_with_fallback(batch_chunks, start_idx, history=None):
            with session_log_context(session_id):
                if not batch_chunks:
                    return
                
                _log(session_id, f"Processing batch of {len(batch_chunks)} chunks ({start_idx} to {start_idx + len(batch_chunks) - 1}) with Gemini 3.1 Pro Preview Array Batching...")
                
                try:
                    results = await ai_transcription.transcribe_gemini_flash_batch(
                        chunks=batch_chunks, 
                        history=history, 
                        entity=entity,
                        category_id=state.get("category_id"),
                        session_id=session_id
                    )
                    
                    from app.services.video.dictionary_cache import inject_lrm
                    for i, res in enumerate(results):
                        c = batch_chunks[i]
                        raw_text = res.get("text", "")
                        
                        # Phase 7: Root-Level LRM Injection
                        c["kurdish_raw"] = inject_lrm(raw_text, state.get("category_id"))
                        
                        c["words"] = res.get("words", [])
                        global_idx = start_idx + i
                        _log(session_id, f"Chunk {global_idx} [{c['chunk_id'][:6]}]: {c['kurdish_raw']}")
                        
                        with open(dir_trans / f"chunk_{global_idx}_transcription.txt", "w", encoding="utf-8") as f:
                            f.write(c["kurdish_raw"])
                            
                except Exception as e:
                    _log(session_id, f"Batch failed ({e}). Attempting binary split fallback...", "WARNING")
                    if len(batch_chunks) == 1:
                        _log(session_id, f"Chunk {start_idx} failed individually. Skipping.", "ERROR")
                        return
                    
                    mid = len(batch_chunks) // 2
                    await _process_batch_with_fallback(batch_chunks[:mid], start_idx, history)
                    next_history = batch_chunks[max(0, mid - 2):mid]
                    await _process_batch_with_fallback(batch_chunks[mid:], start_idx + mid, next_history)

        batches = []
        current_batch = []
        current_duration = 0.0
        
        for c in chunks:
            dur = c.get("speech_duration", 5.0)
            if len(current_batch) >= 20 or current_duration + dur > 120.0:
                batches.append(current_batch)
                current_batch = [c]
                current_duration = dur
            else:
                current_batch.append(c)
                current_duration += dur
        if current_batch:
            batches.append(current_batch)
            
        start_index = 1
        for i, batch in enumerate(batches):
            history = chunks[max(0, start_index - 3):start_index - 1] if start_index > 1 else None
            await _process_batch_with_fallback(batch, start_index, history)
            start_index += len(batch)
    except Exception as e:
        _log(session_id, f"Transcription failed: {e}", "ERROR")
        raise HTTPException(status_code=500, detail="Internal server error")
        
    state["chunks"] = chunks
    _clear_individual_chunk_files(_get_session_dir(session_id))
    _write_state(session_id, state)
    return state

@router.post("/step4-upload-transcription")
async def step4_upload_transcription(file: UploadFile = File(...), session_id: Optional[str] = Form(None), user: AuthenticatedUser = Depends(require_user)): 
    if not session_id or session_id == "null":
        session_id = f"job_{uuid.uuid4().hex[:8]}"
        
    _log(session_id, f"Starting transcription ZIP upload...")
    
    session_dir = _get_session_dir(session_id)
    zip_path = session_dir / file.filename
    with open(zip_path, "wb") as f:
        # Pird: bounded read. See Fix 4.
        _MAX = 1024 * 1024 * 1024
        _total = 0
        while True:
            _c = await file.read(64 * 1024)
            if not _c:
                break
            _total += len(_c)
            if _total > _MAX:
                raise HTTPException(status_code=413, detail=f"Upload exceeds {_MAX} bytes")
            f.write(_c)
        
    _log(session_id, f"Extracting {file.filename}...")
    
    trans_dir = session_dir / "uploaded_transcription"
    trans_dir.mkdir(exist_ok=True)
    
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(trans_dir)
    except Exception as e:
        _log(session_id, f"ZIP extraction failed: {e}", "ERROR")
        raise HTTPException(status_code=400, detail="Invalid ZIP file")
        
    json_path = trans_dir / "transcription.json"
    if not json_path.exists():
        _log(session_id, "transcription.json not found in ZIP!", "ERROR")
        raise HTTPException(status_code=400, detail="transcription.json not found in ZIP")
        
    import json
    with open(json_path, 'r', encoding='utf-8') as f:
        uploaded_chunks = json.load(f)
        
    _log(session_id, f"Loaded {len(uploaded_chunks)} chunks from transcription.json. Copying audio files...")
    
    chunks = []
    for i, c in enumerate(uploaded_chunks):
        audio_filename = Path(c["audio_file"]).name
        extracted_wav = trans_dir / audio_filename
        
        if not extracted_wav.exists():
            _log(session_id, f"Missing audio file: {audio_filename}", "ERROR")
            continue
            
        static_chunk = Path(f"static/outputs/chunk_{session_id}_{i}.wav")
        static_chunk.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copy(str(extracted_wav), str(static_chunk))
        
        c["file_path"] = str(static_chunk)
        c["audio_url"] = f"/static/outputs/chunk_{session_id}_{i}.wav"
        
        # UI expects "speech_duration" and "speaker" as fallback
        c["speech_duration"] = c.get("duration_sec", 0.0)
        c["start_time"] = c.get("start", 0.0)
        c["end_time"] = c.get("end", 0.0)
        
        chunks.append(c)
        
    _log(session_id, f"Successfully processed {len(chunks)} transcribed chunks.")
    
    state = _read_state(session_id)
    if not state:
        state = {"session_id": session_id}
        
    state["chunks"] = chunks
    state["transcribed"] = True
    _clear_individual_chunk_files(session_dir)
    _write_state(session_id, state)
    
    return state

# Step 5: The 2-Stage Deterministic Timing Engine
@router.post("/step5-run-physics")
async def step5_run_physics(session_id: str = Form(...), chunks_json: Optional[str] = Form(None), user: AuthenticatedUser = Depends(require_user)): 
    import subprocess
    _log(session_id, "Starting 2-Stage Physics Engine: Translate -> Evaluate -> Recurse/Assemble")
    state = _read_state(session_id)
    chunks = state.get("chunks", [])
    
    # Capture user manual edits from the Dashboard before running the engine
    if chunks_json:
        try:
            import json
            updated_chunks = json.loads(chunks_json)
            update_map = {str(c["chunk_id"]): c for c in updated_chunks}
            for c in chunks:
                cid = str(c["chunk_id"])
                if cid in update_map:
                    if update_map[cid].get("kurdish_raw"):
                        c["kurdish_raw"] = update_map[cid]["kurdish_raw"]
                    if update_map[cid].get("arabic_text"):
                        c["user_arabic_text"] = update_map[cid]["arabic_text"]
            _write_state(session_id, state)
            _log(session_id, "Applied manual transcription/translation edits from Dashboard.")
        except Exception as e:
            _log(session_id, f"Failed to parse chunks_json: {e}", "WARNING")
    
    from app.services.vcta.translator import translate_single_chunk_structured
    from app.services.vcta.tts_engine import generate_tts, _get_audio_duration
    from app.services.vcta.voice_router import extract_speaker_references, route_voice
    from scripts.audio_assembly import process_chunk_assembly
    from app.services.vcta.assembler import assemble_final_video
    import shutil
    
    # Celery Async Dispatch imports
    from celery import chord
    from app.worker import process_chunk_task, assemble_video_task
    from app.core.database import create_job
    
    _log(session_id, "Extracting speaker references for Voice Cloning...")
    extract_speaker_references(chunks, str(_get_session_dir(session_id)))
    session_state_dict = {"work_dir": str(_get_session_dir(session_id))}
    
    tts_dir = _get_session_dir(session_id) / "tts"
    tts_dir.mkdir(exist_ok=True)
    assembled_dir = _get_session_dir(session_id) / "assembled"
    assembled_dir.mkdir(exist_ok=True)
    
    # Pre-resolve video_path and bg_wav for the Async Assembler
    video_path = state.get("video_path", "")
    if not video_path or not os.path.exists(video_path):
        session_dir_path = _get_session_dir(session_id)
        if session_dir_path.exists():
            for f in os.listdir(session_dir_path):
                if f.lower().endswith(".mp4") and not f.startswith("final_"):
                    video_path = str(session_dir_path / f)
                    state["video_path"] = video_path
                    _write_state(session_id, state)
                    break
    _log(session_id, f"[DEBUG] Resolved video_path: {video_path}")

    bg_wav = state.get("bg_wav", "")
    if not bg_wav or not os.path.exists(bg_wav):
        bg_fallback = _get_session_dir(session_id) / "background_sfx_music.wav"
        if bg_fallback.exists():
            bg_wav = str(bg_fallback)
            state["bg_wav"] = bg_wav
            _write_state(session_id, state)
            
    # Async Local Dispatch (Bypass Celery for Local Windows)
    _log(session_id, "Dispatching chunks to local async execution...")
    
    from app.worker import _async_process_chunk, _async_assemble_video
    # ---------------------------------------------------------
    # GOOGLE GENAI TEXT BATCHING & AUDIT TRAP
    # ---------------------------------------------------------
    from app.services.vcta import translator
    import math
    
    _log(session_id, "Running Google GenAI JSON Text Batching...")
    chunks = await translator.batch_translate_text(chunks, batch_size=4)
    
    _log(session_id, "Running Batch JSON Audit Trap...")
    for c in chunks:
        if not c.get("kurdish_raw"):
            continue
            
        c_id = str(c.get("chunk_id"))
        arabic = c.get("arabic_text", "")
        
        if not arabic:
            _log(session_id, f"Audit Trap: Chunk {c_id} missing from JSON batch or empty.", "WARNING")
            c["bypass_initial_translation"] = False
            continue
            
        # Check if out of bounds
        video_slot_duration = c.get("speech_duration", c.get("duration_sec", 0.0))
        if video_slot_duration <= 0:
            continue
            
        target_words = video_slot_duration * 1.8
        min_w = max(1, math.floor(target_words) - 1)
        max_w = max(min_w, math.ceil(target_words) - 1)
        
        # Clean punctuation to match worker logic
        import re
        clean_arabic = re.sub(r'[^\w\s\u0600-\u06FF]', '', arabic)
        actual_words = len(clean_arabic.split())
        
        if actual_words < min_w or actual_words > max_w:
            _log(session_id, f"Audit Trap: Chunk {c_id} word count ({actual_words}) out of bounds [{min_w}, {max_w}]. Relying on physical TTS duration check.", "INFO")
        c["bypass_initial_translation"] = True

    try:
        valid_chunks = []
        for i, chunk in enumerate(chunks):
            if not chunk.get("kurdish_raw"):
                continue
                
            video_slot_duration = chunk.get("speech_duration", chunk.get("duration_sec", 0.0))
            if video_slot_duration <= 0:
                continue
                
            # Create DB entry for state tracking if it doesn't exist
            from app.core.database import get_job
            existing_job = await get_job(chunk["chunk_id"])
            if not existing_job:
                await create_job(chunk["chunk_id"], store_id=session_id)
            valid_chunks.append(chunk)
            
        if valid_chunks:
            async def run_pipeline_bg():
                with session_log_context(session_id):
                    try:
                        _log(session_id, "Processing chunks with concurrency limit of 2...")
                        sem = asyncio.Semaphore(2)
                        async def bounded_process(c):
                            async with sem:
                                return await _async_process_chunk(c, session_id, session_state_dict, video_path, translate_only=True)
                                
                        chunk_tasks = [bounded_process(c) for c in valid_chunks]
                        results = await asyncio.gather(*chunk_tasks)
                        
                        _log(session_id, "Translation completed. Background TTS and Physics skipped as requested.")
                    except Exception as ex:
                        _log(session_id, f"Pipeline execution failed: {ex}", "ERROR")

            asyncio.create_task(run_pipeline_bg())
            _log(session_id, f"Dispatched {len(valid_chunks)} background pipeline tasks.")
        else:
            _log(session_id, "No valid chunks found to dispatch.", "WARNING")
            
    except Exception as e:
        _log(session_id, f"Worker dispatch failed: {e}", "ERROR")
        raise HTTPException(status_code=500, detail="Internal server error")
        
    state["chunks"] = chunks
    _write_state(session_id, state)
    return state

@router.post("/step6-run-tts")
async def step6_run_tts(
    session_id: str = Form(...),
    chunks_json: Optional[str] = Form(None),
    user: AuthenticatedUser = Depends(require_user)
):
    _log(session_id, "Starting Manual Step 6: Voice Generation (TTS Only)")
    state = _read_state(session_id)
    chunks = state.get("chunks", [])
    session_dir = _get_session_dir(session_id)
    
    # Merge individual chunk JSONs that were written by the background worker
    import json
    for c in chunks:
        chunk_id = c.get("chunk_id")
        json_file = session_dir / f"chunk_{chunk_id}.json"
        if json_file.exists():
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    updated_chunk = json.load(f)
                    c.update(updated_chunk)
            except Exception:
                pass
                
    # Capture user manual edits from the Dashboard before running Voice Gen
    if chunks_json:
        try:
            import json
            updated_chunks = json.loads(chunks_json)
            update_map = {str(c["chunk_id"]): c for c in updated_chunks}
            for c in chunks:
                cid = str(c["chunk_id"])
                if cid in update_map:
                    if update_map[cid].get("arabic_text"):
                        c["arabic_text"] = update_map[cid]["arabic_text"]
            _write_state(session_id, state)
            _log(session_id, "Applied manual translation edits from Dashboard.")
        except Exception as e:
            _log(session_id, f"Failed to parse chunks_json: {e}", "WARNING")

    
    if not chunks:
        raise HTTPException(status_code=400, detail="No chunks found to process.")
        
    session_dir = _get_session_dir(session_id)
    session_state_dict = {"work_dir": str(session_dir)}
    video_path = state.get("video_path", "")
    
    from app.worker import _async_process_chunk
    try:
        valid_chunks = [c for c in chunks if c.get("arabic_text")]
        
        if valid_chunks:
            async def run_tts_bg():
                with session_log_context(session_id):
                    try:
                        _log(session_id, f"Generating voices for {len(valid_chunks)} chunks with Physics duration autofix...")
                        sem = asyncio.Semaphore(2)
                        async def bounded_process(c):
                            async with sem:
                                return await _async_process_chunk(
                                    c, session_id, session_state_dict, video_path,
                                    translate_only=False,
                                    bypass_initial_translation=True
                                )
                                
                        chunk_tasks = [bounded_process(c) for c in valid_chunks]
                        results = await asyncio.gather(*chunk_tasks)
                        
                        _log(session_id, "All Voice Generation completed with Autofix limits.")
                    except Exception as ex:
                        _log(session_id, f"TTS execution failed: {ex}", "ERROR")

            asyncio.create_task(run_tts_bg())
            _log(session_id, f"Dispatched {len(valid_chunks)} background TTS tasks.")
        else:
            _log(session_id, "No valid chunks with arabic_text found for TTS.", "WARNING")
            
    except Exception as e:
        _log(session_id, f"TTS dispatch failed: {e}", "ERROR")
        raise HTTPException(status_code=500, detail="Internal server error")
        
    return state

@router.post("/step7-run-assembly")
async def step7_run_assembly(
    session_id: str = Form(...),
    user: AuthenticatedUser = Depends(require_user)
):
    _log(session_id, "Starting Manual Step 7: Final Assembly")
    state = _read_state(session_id)
    chunks = state.get("chunks", [])
    session_dir = _get_session_dir(session_id)
    
    # Merge individual chunk JSONs that were written by the background worker
    import json
    for c in chunks:
        chunk_id = c.get("chunk_id")
        json_file = session_dir / f"chunk_{chunk_id}.json"
        if json_file.exists():
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    updated_chunk = json.load(f)
                    c.update(updated_chunk)
            except Exception:
                pass
                
    video_path = state.get("video_path", "")
    bg_wav = state.get("bg_wav", "")
    
    reference_profile = state.get("reference_profile")
    if not reference_profile and video_path:
        from app.services.vcta.reference_mastering import extract_loudness_profile
        _log(session_id, "Extracting loudness reference profile from original video...")
        try:
            reference_profile = extract_loudness_profile(video_path)
            state["reference_profile"] = reference_profile
            _write_state(session_id, state)
        except Exception as e:
            _log(session_id, f"Failed to extract loudness profile: {e}", "ERROR")
            reference_profile = {}
    
    from app.worker import _async_assemble_video, _async_process_chunk
    try:
        async def run_assembly_bg():
            with session_log_context(session_id):
                try:
                    _log(session_id, "Re-mastering chunks with latest timing parameters before assembly (Free/Local)...")
                    remaster_tasks = []
                    for c in chunks:
                        if c.get("arabic_text") and os.path.exists(Path(session_dir) / "tts" / f"raw_tts_{c['chunk_id']}.wav"):
                            remaster_tasks.append(_async_process_chunk(
                                chunk=c, 
                                session_id=session_id, 
                                session_state_dict=state, 
                                video_path=video_path, 
                                remaster_only=True
                            ))
                    
                    if remaster_tasks:
                        remaster_results = await asyncio.gather(*remaster_tasks)
                        # Merge results to update chunk status and paths
                        for res in remaster_results:
                            for c in chunks:
                                if c.get("chunk_id") == res.get("chunk_id"):
                                    c.update(res)
                                    break
                                    
                    _write_state(session_id, state)
                    
                    _log(session_id, "Assembling final video with Atempo limits...")
                    await _async_assemble_video(chunks, session_id, video_path, bg_wav, reference_profile)
                    _log(session_id, "Video assembly completed.")
                except Exception as ex:
                    _log(session_id, f"Assembly execution failed: {ex}", "ERROR")

        asyncio.create_task(run_assembly_bg())
        _log(session_id, "Dispatched background Assembly task.")
    except Exception as e:
        _log(session_id, f"Assembly dispatch failed: {e}", "ERROR")
        raise HTTPException(status_code=500, detail="Internal server error")
        
    return state

@router.get("/status/{session_id}")
async def get_physics_status(session_id: str, user: AuthenticatedUser = Depends(require_user)): 
    import json
    from app.core.database import get_job
    state = _read_state(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="This dubbing project could not be found. It may have been deleted or expired.")
        
    chunks = state.get("chunks", [])
    session_dir = _get_session_dir(session_id)
    
    for c in chunks:
        chunk_id = c.get("chunk_id")
        if not chunk_id:
            continue
        json_file = session_dir / f"chunk_{chunk_id}.json"
        if json_file.exists():
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    updated_chunk = json.load(f)
                    c.update(updated_chunk)
                    # Convert absolute paths to static routes for the frontend
                    if "tts_url" not in c and "tts_file" in updated_chunk:
                        # Assuming tts_file is something like data/jobs/sessions/...
                        # Map this for the frontend if necessary, or let the UI handle it.
                        pass
            except Exception:
                pass
                
    state["chunks"] = chunks
    
    assembly_job = await get_job(session_id)
    if assembly_job:
        status = assembly_job.get("status")
        state["job_status"] = status
        if status == "completed":
            # Set the final_url for the frontend
            state["final_url"] = f"/video/manual/download/{session_id}/assembled/final_dubbed.mp4"
            if not state.get("logged_to_history"):
                try:
                    from app.core import database_convex
                    client = database_convex._get_service_role_client()
                    row = await database_convex.create_job(
                        client,
                        workspace_id=user.workspace_id,
                        owner_user_id=user.user_id,
                        source_video_r2_key=state.get("video_url", "")
                    )
                    await database_convex.update_job_status(
                        client,
                        workspace_id=user.workspace_id,
                        job_id=row["id"],
                        status="completed",
                        progress=100,
                        output_path=state["final_url"]
                    )
                    state["logged_to_history"] = True
                    _write_state(session_id, state)
                except Exception as e:
                    _log(session_id, f"Failed to log to History: {e}", "WARNING")
            
    return state

@router.post("/step5-retry-chunk")
async def retry_single_chunk(
    session_id: str = Form(...),
    chunk_id: str = Form(...),
    arabic_text: Optional[str] = Form(None),
    generate_voice: bool = Form(False),
    user: AuthenticatedUser = Depends(require_user)
):
    """
    Retries the translation/TTS for a SINGLE chunk.
    If arabic_text is provided, it skips translation and forces that exact text into TTS.
    """
    _log(session_id, f"Granular Retry Triggered for chunk: {chunk_id}")
    
    state = _read_state(session_id)
    chunks = state.get("chunks", [])
    
    # Find the target chunk
    target_chunk = None
    for c in chunks:
        if str(c.get("chunk_id")) == str(chunk_id):
            target_chunk = c
            break
            
    if not target_chunk:
        raise HTTPException(status_code=404, detail=f"Chunk {chunk_id} not found in state.")
        
    session_dir = _get_session_dir(session_id)
    session_state_dict = {"work_dir": str(session_dir)}
    video_path = state.get("video_path", "")
    
    if arabic_text:
        target_chunk["arabic_text"] = arabic_text
        _log(session_id, f"Saved manual translation for chunk {chunk_id}.")
        
    if generate_voice:
        _log(session_id, f"Generating TTS for single chunk {chunk_id}...")
        from app.worker import _async_process_chunk
        try:
            target_chunk = await _async_process_chunk(
                chunk=target_chunk,
                session_id=session_id,
                session_state_dict=session_state_dict,
                video_path=video_path,
                translate_only=False,
                bypass_initial_translation=True,
                skip_math=True
            )
            _log(session_id, f"Successfully generated TTS for chunk {chunk_id}.")
        except Exception as e:
            _log(session_id, f"Failed to generate TTS for chunk {chunk_id}: {e}", "ERROR")
            raise HTTPException(status_code=500, detail=f"TTS Generation failed: {e}")
        
    try:
        # Update the main state list
        for i, c in enumerate(chunks):
            if str(c.get("chunk_id")) == str(chunk_id):
                chunks[i] = target_chunk
                break
                
        state["chunks"] = chunks
        _write_state(session_id, state)
        
        # Also update the individual chunk file
        try:
            import json
            chunk_json_path = session_dir / f"chunk_{chunk_id}.json"
            if chunk_json_path.exists():
                with open(chunk_json_path, "r", encoding="utf-8") as f:
                    c_data = json.load(f)
                c_data["arabic_text"] = arabic_text
                with open(chunk_json_path, "w", encoding="utf-8") as f:
                    json.dump(c_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            pass
            
        return {"session_id": session_id, "chunk": target_chunk}
    except Exception as e:
        _log(session_id, f"Failed to save chunk {chunk_id}: {e}", "ERROR")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/step5-save-all-chunks")
async def save_all_chunks(
    request: Request,
    user: AuthenticatedUser = Depends(require_user)
):
    try:
        data = await request.json()
        session_id = data.get("session_id")
        updates = data.get("updates", [])
        
        if not session_id or not updates:
            raise HTTPException(status_code=400, detail="Missing session_id or updates")
            
        state = _read_state(session_id)
        chunks = state.get("chunks", [])
        session_dir = _get_session_dir(session_id)
        
        update_map = {str(u["chunk_id"]): u["arabic_text"] for u in updates}
        
        # Update state chunks
        for c in chunks:
            cid = str(c.get("chunk_id"))
            if cid in update_map:
                c["arabic_text"] = update_map[cid]
                
        state["chunks"] = chunks
        _write_state(session_id, state)
        
        # Update individual JSON files
        import json
        for cid, text in update_map.items():
            chunk_json_path = session_dir / f"chunk_{cid}.json"
            if chunk_json_path.exists():
                try:
                    with open(chunk_json_path, "r", encoding="utf-8") as f:
                        c_data = json.load(f)
                    c_data["arabic_text"] = text
                    with open(chunk_json_path, "w", encoding="utf-8") as f:
                        json.dump(c_data, f, ensure_ascii=False, indent=2)
                except Exception:
                    pass
                    
        _log(session_id, f"Saved manual translations for {len(updates)} chunks.")
        return {"session_id": session_id, "status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/step5-assemble-only")
async def assemble_video_only(session_id: str = Form(...), user: AuthenticatedUser = Depends(require_user)): 
    """
    Quickly re-stitches the video using the currently available processed chunks,
    without re-running the entire translation and TTS pipeline.
    """
    _log(session_id, "Triggering fast assembly of existing chunks...")
    
    state = _read_state(session_id)
    video_path = state.get("video_path", "")
    bg_wav = state.get("bg_wav", "")
    
    # Read the latest chunk JSON files to ensure we get the latest TTS paths
    session_dir = Path("data/jobs/sessions") / session_id
    valid_chunks = []
    
    for f in os.listdir(session_dir):
        if f.startswith("chunk_") and f.endswith(".json"):
            with open(session_dir / f, "r", encoding="utf-8") as fp:
                valid_chunks.append(json.load(fp))
                
    # Sort chronologically by start time
    valid_chunks.sort(key=lambda x: float(x.get("start", 0.0)))
    
    from app.worker import _async_assemble_video
    
    async def run_assembly_bg():
        with session_log_context(session_id):
            try:
                _log(session_id, "Re-mastering chunks before final assembly (Standalone Assembly Mode)...")
                await _async_assemble_video(valid_chunks, session_id, video_path, bg_wav)
                _log(session_id, "Fast Assembly complete!", "INFO")
            except Exception as e:
                _log(session_id, f"Fast Assembly failed: {e}", "ERROR")
            
    # Run in background so the UI doesn't hang
    asyncio.create_task(run_assembly_bg())
    
    return {"message": "Assembly triggered in background"}

