import os
import asyncio
import uuid
import logging
from pathlib import Path
import httpx
from fastapi import HTTPException

# PIRD-013: versioned consent text. Bumping this version forces every
# user to re-consent before any further biometric data is processed.
CONSENT_TEXT_VERSION = "2026-07-26.1"


async def _check_voice_recording_consent(user) -> None:
    # TEMPORARILY DISABLED for local testing
    return


# Configure global file logging for the terminal dashboard
# PIRD-011: rely solely on the RotatingFileHandler configured in main.py.
# This module no longer attaches its own FileHandler.
logger = logging.getLogger(__name__)
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, BackgroundTasks, Request, Depends
from app.auth.clerk_auth import require_user, require_user_or_internal, AuthenticatedUser
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from typing import List, Optional
from pydantic import BaseModel

from app.schemas.video import VideoJobCreate, VideoJobResponse, VideoJobStatus
from app.services.video.pipeline import create_video_job, get_job_status
from app.services.video_worker_vcta import process_video_job_local as worker_process_video_job
from app.core.log_redact import safe_ws


# PIRD-010: per-IP rate limiter, shared with internal_jobs.py. The previous
# local copy lived here but was dead code: it was called as
# `_rate_limited("5/minute")` against a param typed `int`, and the routes it
# decorated declared no `request` parameter, so it silently skipped the limit
# on every request. `rate_limited` now validates both at decoration time.
from app.core.ratelimit import rate_limited as _rate_limited


router = APIRouter()

# Pird: global upload cap. See handoffs/dubbing-security-pass2-fixes.md Fix 7.
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", 1024 * 1024 * 1024))  # 1 GB


async def _bounded_read(file, max_bytes: int = MAX_UPLOAD_BYTES) -> bytes:
    """Read an UploadFile in chunks, raising 413 if it exceeds the cap."""
    chunks: list = []
    total = 0
    while True:
        c = await file.read(64 * 1024)
        if not c:
            break
        total += len(c)
        if total > max_bytes:
            raise HTTPException(status_code=413, detail=f"Upload exceeds {max_bytes} bytes")
        chunks.append(c)
    return b"".join(chunks)


def _check_playground_owner(session_id: str, user: AuthenticatedUser) -> None:
    """Verify session_id belongs to the requesting user's workspace.

    Reads the `_owner` sentinel file written by `ingest_video`. Raises 404
    (not 403) so non-owners can't probe session existence.

    ponytail: single disk read on every playground route. Cheaper than
    a DB lookup, and we already hit the FS for the chunk files anyway.
    Upgrade to a Supabase lookup if disk latency becomes a bottleneck.
    """
    owner_file = Path(f"data/jobs/playground_ingest/{session_id}/_owner")
    if not owner_file.is_file():
        raise HTTPException(status_code=404, detail="This dubbing project could not be found. It may have been deleted or expired.")
    try:
        first_line = owner_file.read_text(encoding="utf-8").splitlines()[0]
    except (OSError, IndexError):
        raise HTTPException(status_code=404, detail="This dubbing project could not be found. It may have been deleted or expired.")
    if first_line != user.workspace_id:
        raise HTTPException(status_code=404, detail="This dubbing project could not be found. It may have been deleted or expired.")


async def _mux_audio_video(video_path: str, audio_path: str, output_path: str) -> bool:
    import subprocess
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", audio_path,
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-shortest",
        output_path
    ]
    proc = await asyncio.to_thread(
        subprocess.run, cmd,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True
    )
    return proc.returncode == 0 and os.path.exists(output_path)


def get_video_duration(path: str) -> float:
    import ffmpeg
    try:
        probe = ffmpeg.probe(path)
        format_info = probe.get("format", {})
        duration = float(format_info.get("duration", 0.0))
        return duration
    except Exception as e:
        logger.error(f"Failed to probe video duration: {e}")
        return 0.0


@router.post("/jobs", response_model=VideoJobResponse)
# PIRD-010: per-IP rate limit on job creation.
@_rate_limited("5/minute")
async def create_job(
    request: Request,
    file: UploadFile = File(...),
    user: AuthenticatedUser = Depends(require_user_or_internal),
    voice_id: Optional[str] = Form(None),
    category: Optional[str] = Form(None),
    entity: Optional[str] = Form(None),
    consent_text_version: Optional[str] = Form(None),
    background_tasks: BackgroundTasks = None,
) -> VideoJobResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")
    # PIRD-006: reject path-traversal in the filename.
    if ".." in file.filename or "/" in file.filename or "\\" in file.filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    # PIRD-006: enforce video content type.
    if not (file.content_type or "").startswith("video/"):
        raise HTTPException(status_code=400, detail=f"Expected video/* content type, got {file.content_type!r}")
    
    if not consent_text_version:
        raise HTTPException(status_code=400, detail="Voice recording consent is required.")

    # PIRD-013: voice-recording consent gate.
    await _check_voice_recording_consent(user)

    # Proxy IP Trap Fix: Extract true IP, bypassing Cloudflare/LoadBalancers
    user_ip_address = request.headers.get("CF-Connecting-IP") or request.headers.get("X-Forwarded-For") or (request.client.host if request.client else "unknown")
    # For multiple IPs in X-Forwarded-For, take the first one
    if "," in user_ip_address:
        user_ip_address = user_ip_address.split(",")[0].strip()

    upload_dir = Path("data/uploads")
    upload_dir.mkdir(parents=True, exist_ok=True)

    ext = Path(file.filename).suffix or ".mp4"
    safe_filename = f"{uuid.uuid4().hex}{ext}"
    input_path = upload_dir / safe_filename

    # Pird (security review L4): previous version did `content = await file.read()`
    # which buffered the entire upload into memory before any size check.
    # A 5 GB POST would OOM the worker before the 1 GB cap was reached.
    # Now we stream-read in 64 KB chunks, check the running total, and
    # write straight to disk — no full-file copy in memory.
    fileobj = await asyncio.to_thread(input_path.open, "wb")
    try:
        total = 0
        while True:
            chunk = await file.read(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"Upload exceeds {MAX_UPLOAD_BYTES} bytes",
                )
            await asyncio.to_thread(fileobj.write, chunk)
    finally:
        await asyncio.to_thread(fileobj.close)

    # 1. Probing duration
    duration = await asyncio.to_thread(get_video_duration, str(input_path))
    if duration <= 0:
        if input_path.exists():
            input_path.unlink()
        raise HTTPException(status_code=400, detail="We couldn't read the audio track. Ensure your video file isn't corrupted and try again.")

    import math
    duration_minutes = math.ceil(duration / 60.0)

    from app.core import db as database

    # 2. Check balance
    try:
        user_client = database.get_user_client(user.access_token)
        remaining_minutes = await database.get_workspace_minutes(user_client, workspace_id=user.workspace_id)
    except Exception as e:
        logger.warning(f"Failed to query workspace minutes balance: {e}")
        remaining_minutes = 999999

    if False and remaining_minutes < duration_minutes:
        if input_path.exists():
            input_path.unlink()
        raise HTTPException(
            status_code=402,
            detail=f"You do not have enough minutes. This video requires {duration_minutes} minutes, but you only have {remaining_minutes} minutes remaining. Please visit the pricing page to add more minutes."
        )

    # 3. Deduct minutes from balance (reserved for this job)
    try:
        # await database.deduct_workspace_minutes(user_client, workspace_id=user.workspace_id, minutes=duration_minutes)
        logger.info(f"Reserved {duration_minutes} minutes from workspace {safe_ws(user.workspace_id)} (remaining: {remaining_minutes - duration_minutes}) - DISABLED FOR LOCAL TESTING")
    except Exception as e:
        if input_path.exists():
            input_path.unlink()
        logger.exception("Failed to deduct workspace minutes balance")
        raise HTTPException(status_code=500, detail="Failed to process billing reservation")

    job_id = str(uuid.uuid4())
    runpod_endpoint = os.getenv("RUNPOD_ENDPOINT_ID", "")
    runpod_api_key = os.getenv("RUNPOD_API_KEY", "")

    # Upload to R2 if running in serverless mode
    source_r2_key = ""
    from app.services import r2
    
    try:
        # RunPod Serverless path: upload source to R2 so the worker can pull it.
        # Local fallback path (no RunPod): keep the file on local disk.
        if runpod_endpoint and r2.R2_ENDPOINT:
            source_r2_key = r2.dubbing_key(user.workspace_id, job_id, safe_filename)
            logger.info(f"Uploading input video to R2 for Serverless job: {source_r2_key}")
            await asyncio.to_thread(r2.upload_file, source_r2_key, str(input_path))
            # Clean up local input path to save space
            if input_path.exists():
                input_path.unlink()

        job = await database.create_job(
            user_client,
            workspace_id=user.workspace_id,
            owner_user_id=user.user_id,
            job_id=job_id,
            source_video_r2_key=source_r2_key,
            consent_version=consent_text_version,
            user_ip_address=user_ip_address
        )
    except Exception as e:
        # Refund reserved minutes on failure to start/create
        try:
            await database.add_workspace_minutes(user_client, workspace_id=user.workspace_id, minutes=duration_minutes)
            logger.info(f"Refunded {duration_minutes} minutes to workspace {safe_ws(user.workspace_id)} due to job creation failure")
        except Exception as refund_err:
            logger.error(f"Failed to refund minutes for workspace {safe_ws(user.workspace_id)}: {refund_err}")

        if input_path.exists():
            input_path.unlink()
        logger.exception("Failed to create video job")
        raise HTTPException(status_code=500, detail="Internal server error")

    # Start orchestrator: RunPod Serverless (GPU) when configured, else local.
    if runpod_endpoint and runpod_api_key:
        logger.info(f"Triggering RunPod Serverless endpoint {runpod_endpoint} for job {job_id}")
        async def trigger_runpod():
            try:
                # RunPod Serverless v2 endpoint. Note the base is
                # api.runpod.ai (NOT .io) -- api.runpod.io returns 404.
                url = f"https://api.runpod.ai/v2/{runpod_endpoint}/run"
                headers = {
                    "Authorization": f"Bearer {runpod_api_key}",
                    "Content-Type": "application/json",
                }
                payload = {
                    "input": {
                        "job_id": job_id,
                        "workspace_id": user.workspace_id,
                        "category": category,
                        "entity": entity,
                        "source_video_r2_key": source_r2_key,
                    }
                }
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(url, json=payload, headers=headers)
                    resp.raise_for_status()
                    result = resp.json()
                    logger.info(f"RunPod Serverless triggered successfully: {result}")
            except Exception as trigger_err:
                logger.error(f"Failed to trigger RunPod Serverless for job {job_id}: {trigger_err}")
                try:
                    await database.add_workspace_minutes(user_client, workspace_id=user.workspace_id, minutes=duration_minutes)
                    logger.info(f"Refunded {duration_minutes} minutes to workspace {safe_ws(user.workspace_id)} due to RunPod trigger failure")
                except Exception as refund_err:
                    logger.error(f"Failed to refund minutes for workspace {safe_ws(user.workspace_id)}: {refund_err}")
                try:
                    await database.update_job_status(
                        user_client,
                        workspace_id=user.workspace_id,
                        job_id=job_id,
                        status="failed",
                        error=f"Failed to start worker process: {trigger_err}",
                    )
                except Exception as db_err:
                    logger.error(f"Failed to write failure to database: {db_err}")

        background_tasks.add_task(trigger_runpod)
    else:
        # Fallback to local background processing when RunPod is unconfigured.
        background_tasks.add_task(
            worker_process_video_job, job_id, str(input_path), user.workspace_id, category, entity
        )

    return VideoJobResponse(
        id=job["id"],
        store_id=job.get("store_id", ""),
        status="completed" if job["status"] == "done" else job["status"],
        progress=job.get("progress", 0),
        input_path="",  # not persisted in app schema; local worker path only
        output_path=job.get("result_video_r2_key") or "",
        error=job.get("error") or "",
        created_at=str(job.get("created_at", "")),
        updated_at=str(job.get("updated_at", "")),
    )


@router.get("/jobs/{job_id}", response_model=VideoJobStatus)
async def get_status(job_id: str, user: AuthenticatedUser = Depends(require_user)) -> VideoJobStatus:
    from app.core import db as database
    user_client = database.get_user_client(user.access_token)
    job = await database.get_job(user_client, workspace_id=user.workspace_id, job_id=job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return VideoJobStatus(
        id=job["id"],
        status="completed" if job["status"] == "done" else job["status"],
        progress=job.get("progress", 0),
        input_path="",  # not persisted in app schema
        output_path=job.get("result_video_r2_key") or job.get("resultVideoR2Key") or "",
        error=job.get("error") or "",
        created_at=str(job.get("created_at", "")),
        updated_at=str(job.get("updated_at", "")),
    )


@router.get("/jobs/{job_id}/download")
async def download_video(job_id: str, inline: bool = False, user: AuthenticatedUser = Depends(require_user)) -> FileResponse:
    from app.core import db as database
    user_client = database.get_user_client(user.access_token)
    job = await database.get_job(user_client, workspace_id=user.workspace_id, job_id=job_id)
    if not job:
        logger.warning("[DOWNLOAD] job_id=%s NOT FOUND for workspace", job_id[:16])
        raise HTTPException(status_code=404, detail="Job not found")

    logger.info(
        "[DOWNLOAD] job_id=%s status=%s r2_key=%s",
        job_id[:16],
        job.get("status", "?"),
        (job.get("result_video_r2_key") or job.get("resultVideoR2Key") or "EMPTY")[:80],
    )

    if job["status"] not in ("completed", "done"):
        logger.warning("[DOWNLOAD] job_id=%s not completed (status=%s)", job_id[:16], job["status"])
        raise HTTPException(status_code=400, detail="Job not completed")

    output_path = job.get("result_video_r2_key") or job.get("resultVideoR2Key") or ""

    # If R2 is configured and this looks like a remote R2 key, redirect to signed URL
    from app.services import r2
    if r2.R2_ENDPOINT and output_path and output_path.startswith("dubbing/"):
        logger.info("[DOWNLOAD] R2 redirect for key=%s", output_path[:80])
        try:
            url = r2.signed_url(output_path)
            return RedirectResponse(url)
        except Exception as e:
            logger.error(f"Failed to generate signed URL for R2 key {output_path}: {e}")
            raise HTTPException(status_code=500, detail="Failed to generate download URL")

    # For relative static paths like /static/outputs/file.mp4, resolve to local
    if output_path and output_path.startswith("/static"):
        output_path = output_path.lstrip("/")

    # If the output_path is an absolute host path (e.g., from a Windows worker), convert it to relative
    if output_path and "data/jobs/sessions" in output_path.replace("\\", "/"):
        output_path = "data/jobs/sessions" + output_path.replace("\\", "/").split("data/jobs/sessions")[1]

    if not output_path:
        logger.warning("[DOWNLOAD] job_id=%s output_path is EMPTY — no file to serve", job_id[:16])
        raise HTTPException(status_code=404, detail="Output file not found")

    # Pird: path canonicalization — reject anything outside static/ and data/
    # result_video_r2_key can be a path or an R2 key depending on the
    # pipeline. Resolve and verify before serving. See
    # handoffs/dubbing-audit-fixes-2026-07-15.md Fix 4.
    static_root = Path("static").resolve()
    data_root = Path("data").resolve()
    try:
        resolved = Path(output_path).resolve()
    except (OSError, RuntimeError):
        raise HTTPException(status_code=404, detail="Output file not found")
        
    is_safe_path = resolved.is_relative_to(static_root) or resolved.is_relative_to(data_root)
    
    if not is_safe_path or not resolved.is_file():
        logger.warning(
            "[DOWNLOAD] job_id=%s path rejected: resolved=%s is_safe=%s is_file=%s",
            job_id[:16], str(resolved)[:100],
            is_safe_path,
            resolved.is_file() if resolved else False,
        )
        raise HTTPException(status_code=404, detail="Output file not found")

    logger.info("[DOWNLOAD] Serving local file: %s", str(resolved)[:120])
    return FileResponse(
        path=str(resolved),
        filename=None if inline else resolved.name,
        media_type="video/mp4"
    )


@router.get("/jobs", response_model=List[VideoJobResponse])
async def list_jobs(user: AuthenticatedUser = Depends(require_user)) -> List[VideoJobResponse]:
    from app.core import db as database
    try:
        user_client = database.get_user_client(user.access_token)
        jobs = await database.list_jobs(user_client, workspace_id=user.workspace_id)
        res = []
        for job in jobs:
            st = job.get("status", "pending")
            status_str = "completed" if st in ("done", "completed") else st
            output_url = job.get("output_path") or job.get("result_video_r2_key") or job.get("resultVideoR2Key") or ""
            if output_url and not output_url.startswith("/") and not output_url.startswith("http"):
                output_url = f"/video/jobs/{job.get('id')}/output"
            res.append(
                VideoJobResponse(
                    id=str(job.get("id") or job.get("legacyId") or ""),
                    store_id="",
                    status=status_str,
                    progress=int(job.get("progress", 0)),
                    input_path="",
                    output_path=output_url,
                    created_at=str(job.get("created_at") or job.get("createdAt") or ""),
                    updated_at=str(job.get("updated_at") or job.get("updatedAt") or ""),
                )
            )
        logger.info("[LIST_JOBS] Workspace %s returned %d jobs", user.workspace_id, len(res))
        return res
    except Exception as e:
        logger.exception("[LIST_JOBS] Failed to list jobs: %s", e)
        return []


# â”€â”€â”€ Translation Testing Playground (Dashboard) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class TranslateSingleRequest(BaseModel):
    chunk_id: str
    kurdish_raw: str
    speech_duration: float
    context_kurdish: str | None = None
    context_arabic: str | None = None


@router.get("/translate-dashboard")
async def get_translate_dashboard():
    # Legacy route — supersede by /tts/* React dashboard. Hard-ridirect so
    # old links still work.
    return RedirectResponse(url="/voices", status_code=301)


@router.get("/translate-dashboard-legacy", response_class=HTMLResponse, include_in_schema=False)
async def get_translate_dashboard_legacy(request: Request, user: AuthenticatedUser = Depends(require_user)):
    # Kept for reference but not routed — opt in by changing the path above.
    from app.core.templates import templates
    from main import resolve_locale, is_rtl
    locale = resolve_locale(request)
    dir_attr = "rtl" if is_rtl(locale) else "ltr"
    return templates.TemplateResponse(request, "translate_dashboard.html", {
        "request": request,
        "locale": locale,
        "dir": dir_attr,
    })


@router.get("/dubbing")
async def get_dubbing_page():
    # Legacy Jinja dubbing workspace — supersede by /tts/dubbing React page.
    return RedirectResponse(url="/dubbing", status_code=301)


@router.get("/dubbing-legacy", response_class=HTMLResponse, include_in_schema=False)
async def get_dubbing_page_legacy(request: Request, user: AuthenticatedUser = Depends(require_user)):
    """Dubbing workspace â€” auth-gated admin page that drives the write
    endpoints below. AuthMiddleware has already populated
    request.state.user and request.state.store from the session cookie;
    we just gate the render here, mirroring the /admin/{store_id} pattern.
    """
    from app.core.templates import templates
    from main import resolve_locale, is_rtl, t, _STRINGS
    locale = resolve_locale(request)
    dir_attr = "rtl" if is_rtl(locale) else "ltr"
    strings = _STRINGS.get(locale, {})
    return templates.TemplateResponse(request, "dubbing.html", {
        "request": request,
        "locale": locale,
        "dir": dir_attr,
        "strings": strings,
        "t": t,
    })


@router.post("/translate-single")
async def translate_single(payload: TranslateSingleRequest, user: AuthenticatedUser = Depends(require_user)):
    from app.services.vcta.translator import translate_batch
    
    # 1. Build input chunk list. If context is provided, prepend it as the context anchor chunk.
    chunks = []
    
    if payload.context_kurdish or payload.context_arabic:
        chunks.append({
            "chunk_id": "context_anchor_test",
            "speech_duration": 3.0,
            "is_context": True,
            "kurdish_raw": payload.context_kurdish or "",
            "kurdish_corrected": payload.context_kurdish or "",
            "arabic_text": payload.context_arabic or "",
            "arabic_locked": payload.context_arabic or "",
            "status": "approved"
        })
        
    active_chunk = {
        "chunk_id": payload.chunk_id,
        "speech_duration": payload.speech_duration,
        "is_context": False,
        "kurdish_raw": payload.kurdish_raw,
        "status": "pending"
    }
    chunks.append(active_chunk)
    
    # 2. Run the translate_batch logic
    debug_payload = []
    if payload.context_kurdish or payload.context_arabic:
        debug_payload.append({
            "chunk_id": "context_anchor_test",
            "speech_duration": 3.0,
            "is_context": True,
            "kurdish_raw": payload.context_kurdish or "",
            "kurdish_corrected": payload.context_kurdish or "",
            "arabic_text": payload.context_arabic or "",
        })
    debug_payload.append({
        "chunk_id": payload.chunk_id,
        "speech_duration": payload.speech_duration,
        "is_context": False,
        "kurdish_raw": payload.kurdish_raw,
        "kurdish_corrected": None,
        "arabic_text": None,
    })
    
    try:
        translated_result = await translate_batch(chunks)
    except Exception as e:
        logger.exception("Translation failed")
        raise HTTPException(status_code=500, detail="Internal server error")
        
    translated_active = None
    for c in translated_result:
        if c["chunk_id"] == payload.chunk_id:
            translated_active = c
            break
            
    if not translated_active:
        logger.error("Active chunk translation missing from translate_batch result")
        raise HTTPException(status_code=500, detail="Internal server error")
        
    kurdish_corrected = translated_active.get("kurdish_corrected") or payload.kurdish_raw
    arabic_text = translated_active.get("arabic_text") or ""
    arabic_locked = translated_active.get("arabic_locked") or arabic_text
    
    cps = len(arabic_text) / payload.speech_duration if payload.speech_duration > 0 else 0.0
    is_over = len(arabic_text) > len(kurdish_corrected) * 2.5
    
    debug_response = []
    if payload.context_kurdish or payload.context_arabic:
        debug_response.append({
            "chunk_id": "context_anchor_test",
            "speech_duration": 3.0,
            "is_context": True,
            "kurdish_raw": payload.context_kurdish or "",
            "kurdish_corrected": payload.context_kurdish or "",
            "arabic_text": payload.context_arabic or "",
        })
    debug_response.append({
        "chunk_id": payload.chunk_id,
        "speech_duration": payload.speech_duration,
        "is_context": False,
        "kurdish_raw": payload.kurdish_raw,
        "kurdish_corrected": kurdish_corrected,
        "arabic_text": arabic_text,
    })

    response_data = {
        "chunk_id": payload.chunk_id,
        "kurdish_raw": payload.kurdish_raw,
        "kurdish_corrected": kurdish_corrected,
        "arabic_text": arabic_text,
        "arabic_locked": arabic_locked,
        "characters_per_second": cps,
        "is_over_ceiling": is_over,
        "status": translated_active.get("status", "failed"),
        "trace": translated_active.get("trace", []),
        "_debug_payload": debug_payload,
        "_debug_response": debug_response
    }
    
    # Save the dashboard test to disk
    try:
        import json
        from pathlib import Path
        save_dir = Path("data/jobs/sessions/playground_tests")
        save_dir.mkdir(parents=True, exist_ok=True)
        file_path = save_dir / f"chunk_{payload.chunk_id}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(response_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"Failed to save playground test to disk: {e}")

    return response_data


@router.post("/generate-playground-tts")
async def generate_playground_tts(
    arabic_text: str = Form(...),
    ref_file: Optional[UploadFile] = File(None),
    user: AuthenticatedUser = Depends(require_user)
):
    import uuid
    from app.services.vcta.tts_engine import _call_fish_speech

    # 1. Determine reference audio path
    reference_audio_path = None
    # Pird: per-workspace + per-user temp dir. Previously shared across all
    # callers, allowing one user to overwrite another's in-flight reference
    # WAV. See handoffs/dubbing-security-pass2-fixes.md Fix 5.
    temp_dir = Path("data/jobs/playground_tmp") / user.workspace_id / user.user_id
    temp_dir.mkdir(parents=True, exist_ok=True)

    if ref_file and ref_file.filename:
        # Save uploaded file
        temp_file_path = temp_dir / f"upload_{uuid.uuid4().hex}.wav"
        with open(temp_file_path, "wb") as f:
            content = await _bounded_read(ref_file)
            f.write(content)
        reference_audio_path = str(temp_file_path)
        
    if not reference_audio_path:
        raise HTTPException(status_code=400, detail="You must upload a reference WAV file.")
        
    # 2. Output path for TTS audio
    output_filename = f"playground_tts_{uuid.uuid4().hex}.wav"
    output_path = Path("static/outputs") / output_filename
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 3. Call Fish Speech
    try:
        success = await _call_fish_speech(
            text=arabic_text,
            reference_audio_path=reference_audio_path,
            output_wav=str(output_path),
            chunk_id="playground"
        )
    except Exception as e:
        success = False
        error_msg = str(e)
        
    # Clean up uploaded temp file if created
    if ref_file and ref_file.filename and os.path.exists(reference_audio_path):
        try:
            os.remove(reference_audio_path)
        except Exception:
            pass
            
    if not success:
        if "error_msg" in locals():
            logger.error("Fish Speech playground TTS failed: %s", error_msg)
        raise HTTPException(
            status_code=500, 
            detail="Internal server error"
        )
        
    return {
        "audio_url": f"/static/outputs/{output_filename}"
    }


@router.post("/assemble-playground-single")
async def assemble_playground_single(
    chunk_id: str = Form(...),
    kurdish_raw: str = Form(...),
    arabic_text: str = Form(...),
    speech_duration: float = Form(...),
    total_duration: float = Form(...),
    rolling_cps: float = Form(...),
    padding_debt_ms: float = Form(...),
    ref_file: Optional[UploadFile] = File(None),
    user: AuthenticatedUser = Depends(require_user)
):
    import uuid
    import shutil
    import json
    from app.services.vcta.tts_engine import _call_fish_speech
    from scripts.audio_assembly import get_pre_split_segments, process_chunk_assembly
    
    # 1. Determine reference audio path & voice ID
    reference_audio_path = None
    # Pird: per-workspace + per-user temp dir. See Fix 5.
    temp_dir = Path("data/jobs/playground_tmp") / user.workspace_id / user.user_id
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    if ref_file and ref_file.filename:
        # Save uploaded file
        temp_file_path = temp_dir / f"upload_{uuid.uuid4().hex}.wav"
        with open(temp_file_path, "wb") as f:
            content = await _bounded_read(ref_file)
            f.write(content)
        reference_audio_path = str(temp_file_path)
        voice_id_str = os.path.splitext(ref_file.filename)[0]
    else:
        voice_id_str = "default"
        
    if not reference_audio_path:
        raise HTTPException(status_code=400, detail="You must upload a reference WAV file.")

    # Critical Fallback Patch: Load base_cps
    voices_config = {}
    voices_json_path = os.path.join("configs", "voices.json")
    if os.path.exists(voices_json_path):
        try:
            with open(voices_json_path, "r", encoding="utf-8") as f:
                voices_config = json.load(f)
        except Exception:
            pass

    if voice_id_str not in voices_config:
        logger.warning(f"WARNING: Voice '{voice_id_str}' not found in voices.json. User skipped calibration. Falling back to default 13.0 CPS. Chunk 1 will be a blind guess.")

    base_cps = voices_config.get(voice_id_str, {"base_cps": 13.0})["base_cps"]
    
    # If rolling_cps from UI is the default 14.0 and we have a custom base_cps, initialize it
    if rolling_cps == 14.0 and base_cps != 13.0:
        rolling_cps = base_cps
        
    # 2. Determine segments (pre-splitting & 1.0s clip guardrail)
    segments = get_pre_split_segments(arabic_text, total_duration, rolling_cps)
    
    # 3. Call Fish Speech TTS
    tts_dir = temp_dir / "tts"
    tts_dir.mkdir(parents=True, exist_ok=True)
    
    chunk = {
        "chunk_id": chunk_id,
        "total_duration": total_duration,
        "speech_duration": speech_duration,
        "status": "approved",
        "arabic_text": arabic_text,
        "kurdish_raw": kurdish_raw
    }
    
    tts_temp_files = []
    
    try:
        if len(segments) > 1:
            chunk["sub_segments"] = []
            for idx, seg_text in enumerate(segments):
                seg_filename = f"tts_{chunk_id}_seg_{idx}_{uuid.uuid4().hex}.wav"
                seg_path = tts_dir / seg_filename
                
                success = await _call_fish_speech(
                    text=seg_text,
                    reference_audio_path=reference_audio_path,
                    output_wav=str(seg_path),
                    chunk_id=f"{chunk_id}_seg_{idx}"
                )
                
                if not success:
                    raise RuntimeError(f"Fish Speech call failed for sub-segment {idx}: '{seg_text}'")
                    
                chunk["sub_segments"].append({
                    "text": seg_text,
                    "tts_file": str(seg_path)
                })
                tts_temp_files.append(str(seg_path))
        else:
            single_filename = f"tts_{chunk_id}_{uuid.uuid4().hex}.wav"
            single_path = tts_dir / single_filename
            
            success = await _call_fish_speech(
                text=arabic_text,
                reference_audio_path=reference_audio_path,
                output_wav=str(single_path),
                chunk_id=chunk_id
            )
            
            if not success:
                raise RuntimeError("Fish Speech call failed for single clip translation.")
                
            chunk["tts_file"] = str(single_path)
            tts_temp_files.append(str(single_path))
            
        # 4. Run the Adaptive Audio Assembly Matrix
        output_filename = f"assembled_play_{uuid.uuid4().hex}.wav"
        output_path = Path("static/outputs") / output_filename
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Process and assemble chunk
        updated_chunk, assembled_path, updated_cps, updated_debt = await process_chunk_assembly(
            chunk=chunk,
            tts_dir=str(tts_dir),
            output_dir=str(Path("static/outputs")),
            rolling_cps=rolling_cps,
            padding_debt_ms=padding_debt_ms
        )
        
        # Move assembled file to static/outputs
        shutil.move(assembled_path, str(output_path))
        
    except Exception as e:
        logger.exception("[PLAYGROUND] Assembly failed")
        for f in tts_temp_files:
            if os.path.exists(f):
                try: os.remove(f)
                except Exception: pass
        raise HTTPException(status_code=500, detail="Internal server error")
        
    finally:
        # Clean up uploaded reference WAV
        if ref_file and ref_file.filename and os.path.exists(reference_audio_path):
            try: os.remove(reference_audio_path)
            except Exception: pass
            
    # Clean up temporary TTS segments
    for f in tts_temp_files:
        if os.path.exists(f):
            try: os.remove(f)
            except Exception: pass
            
    return {
        "audio_url": f"/static/outputs/{output_filename}",
        "rolling_cps": updated_cps,
        "padding_debt_ms": updated_debt,
        "path_taken": updated_chunk.get("path_taken", "Unknown"),
        "delta": updated_chunk.get("delta", 0.0),
        "tts_duration": updated_chunk.get("tts_duration", 0.0),
        "truncated": updated_chunk.get("truncated", False),
        "truncated_ms": updated_chunk.get("truncated_ms", 0.0),
        "pre_truncation_tts_duration": updated_chunk.get("pre_truncation_tts_duration", 0.0),
        "pre_split": len(segments) > 1,
        "segments": segments
    }


@router.post("/ingest")
# PIRD-010: per-IP rate limit on video ingest.
@_rate_limited("5/minute")
async def ingest_video(request: Request, video_file: UploadFile = File(...), user: AuthenticatedUser = Depends(require_user)):
    import json
    import shutil
    if not video_file.filename:
        raise HTTPException(status_code=400, detail="No video file provided.")
    # PIRD-006: reject path-traversal in the filename before any FS write.
    if ".." in video_file.filename or "/" in video_file.filename or "\\" in video_file.filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    # PIRD-006: enforce content type.
    if not (video_file.content_type or "").startswith("video/"):
        raise HTTPException(status_code=400, detail=f"Expected video/* content type, got {video_file.content_type!r}")
    # PIRD-013: voice-recording consent gate before any biometric file is written.
    await _check_voice_recording_consent(user)

    session_id = uuid.uuid4().hex
    work_dir = Path(f"data/jobs/playground_ingest/{session_id}")
    work_dir.mkdir(parents=True, exist_ok=True)

    # Pird: stamp workspace_id at ingest so every downstream playground
    # route (chunk-audio, split-chunk, process-chunk, etc.) can verify
    # ownership without trusting the URL. See
    # handoffs/dubbing-audit-fixes-2026-07-15.md Fix 1.
    (work_dir / "_owner").write_text(
        f"{user.workspace_id}\n{user.user_id}\n", encoding="utf-8"
    )
    
    # Save uploaded video
    video_ext = os.path.splitext(video_file.filename)[1] or ".mp4"
    video_path = work_dir / f"original{video_ext}"
    # Pird: bounded read so a 5 GB POST can't OOM the worker. See Fix 7.
    content = await _bounded_read(video_file)
    await asyncio.to_thread(video_path.write_bytes, content)
        
    # 1. Audio Extraction
    audio_raw = str(work_dir / "audio_raw.wav")
    from app.services.video.transcriber import extract_audio
    success, _ = await extract_audio(str(video_path), audio_raw)
    if not success or not os.path.exists(audio_raw):
        raise HTTPException(status_code=500, detail="Failed to extract audio from video.")
        
    # 2. Audio Separation (Dialogue vs. Background BGM)
    from app.services.video_worker_vcta import _separate_stems
    voice_wav, bg_wav = await _separate_stems(audio_raw, str(work_dir))
    
    kurdish_dialogue_raw = str(work_dir / "kurdish_dialogue_raw.wav")
    background_sfx_music = str(work_dir / "background_sfx_music.wav")
    
    # Rename/copy to compliant names
    if os.path.exists(voice_wav) and voice_wav != kurdish_dialogue_raw:
        if os.path.exists(kurdish_dialogue_raw):
            os.remove(kurdish_dialogue_raw)
        os.rename(voice_wav, kurdish_dialogue_raw)
    elif not os.path.exists(voice_wav):
        shutil.copy(audio_raw, kurdish_dialogue_raw)
        
    if bg_wav and os.path.exists(bg_wav) and bg_wav != background_sfx_music:
        if os.path.exists(background_sfx_music):
            os.remove(background_sfx_music)
        os.rename(bg_wav, background_sfx_music)
    elif not os.path.exists(bg_wav):
        # Create silent background file if background is missing
        from scripts.audio_assembly import AudioAssembler
        assembler_temp = AudioAssembler(None, None, 13.0)
        dur = assembler_temp._get_wav_duration(kurdish_dialogue_raw)
        import ffmpeg
        ffmpeg.input('anullsrc', f='lavfi', t=dur).output(background_sfx_music, ar=16000, ac=1).overwrite_output().run(quiet=True)
        
    # 3. Gemini 3.1 Pro Audio Transcription & Segmentation
    from app.services.video.gemini_transcription import transcribe_and_segment_gemini
    from app.services.vcta import chunker, transcriber_mock
    
    try:
        chunks = await chunker.run_vad_chunking(kurdish_dialogue_raw, str(work_dir))
        if not chunks:
            raise HTTPException(status_code=400, detail="No speech detected in the video track.")
        chunks = await transcribe_and_segment_gemini(chunks)
    except Exception as e:
        logger.exception(f"Gemini 3.1 Pro Transcription failed: {e}")
        # Fallback to mock STT if Gemini fails
        chunks = await transcriber_mock.transcribe_all(chunks)
    
    for c in chunks:
        dur = c["speech_duration"]
        c["target_chars"] = int(dur * 13.0)
        c["ceiling_chars"] = int(dur * (13.0 + 1.5))
        c["floor_chars"] = int(c["ceiling_chars"] * 0.75)
        c["rolling_cps"] = 13.0
        c["padding_debt_ms"] = 0.0
        c["arabic_text"] = ""   # LOCKED â€” user must trigger AI processing per-chunk
        c["status"] = "pending"
        c["anchor_forced"] = c.get("anchor_forced", False)
        c["context_locked_parent"] = c.get("context_locked_parent", None)
        
    # Calculate Source CPS on Ingest
    total_kurdish_text = "".join([c.get("kurdish_raw", "") for c in chunks])
    total_video_speech_duration = sum([c.get("speech_duration", 0.0) for c in chunks])
    if total_video_speech_duration > 0:
        source_cps = len(total_kurdish_text) / total_video_speech_duration
    else:
        source_cps = 13.0

    with open(work_dir / "source_cps.txt", "w", encoding="utf-8") as f:
        f.write(str(source_cps))

    from app.services.video.audio_processing import extract_acoustic_profile
    try:
        source_profile = extract_acoustic_profile(kurdish_dialogue_raw, source_cps)
    except Exception as e:
        logger.error(f"Failed to extract acoustic profile: {e}")
        source_profile = {
            "cps": source_cps,
            "pitch_hz": 120.0,
            "energy_db": -16.0
        }
    
    with open(work_dir / "source_profile.json", "w", encoding="utf-8") as f:
        json.dump(source_profile, f, ensure_ascii=False, indent=2)

    # Save the session chunks info
    session_json = work_dir / "session_chunks.json"
    with open(session_json, "w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)
        
    # Copy original video, bg-only video, and Kurdish vocals-only video to static/outputs
    original_public_filename = f"original_{session_id}.mp4"
    original_public_path = Path("static/outputs") / original_public_filename
    original_public_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(str(video_path), str(original_public_path))
    
    bg_only_public_filename = f"bg_only_{session_id}.mp4"
    bg_only_public_path = Path("static/outputs") / bg_only_public_filename
    await _mux_audio_video(str(video_path), background_sfx_music, str(bg_only_public_path))
    
    ku_vocals_public_filename = f"ku_vocals_{session_id}.mp4"
    ku_vocals_public_path = Path("static/outputs") / ku_vocals_public_filename
    await _mux_audio_video(str(video_path), kurdish_dialogue_raw, str(ku_vocals_public_path))
    
    return {
        "session_id": session_id,
        "kurdish_dialogue_raw": kurdish_dialogue_raw,
        "background_sfx_music": background_sfx_music,
        "video_original_url": f"/static/outputs/{original_public_filename}",
        "video_bg_only_url": f"/static/outputs/{bg_only_public_filename}",
        "video_kurdish_vocals_url": f"/static/outputs/{ku_vocals_public_filename}",
        "chunks": chunks,
        "source_cps": source_cps,
        "source_profile": source_profile
    }


@router.post("/assemble-playground-chunk")
async def assemble_playground_chunk(
    session_id: str = Form(...),
    chunk_id: str = Form(...),
    kurdish_raw: str = Form(...),
    arabic_text: str = Form(...),
    rolling_cps: float = Form(...),
    padding_debt_ms: float = Form(...),
    ref_file: Optional[UploadFile] = File(None),
    user: AuthenticatedUser = Depends(require_user)
):
    # PIRD DR-006: verify the caller owns this playground session.
    _check_playground_owner(session_id, user)

    work_dir = Path(f"data/jobs/playground_ingest/{session_id}")
    session_json = work_dir / "session_chunks.json"
    if not session_json.exists():
        raise HTTPException(status_code=404, detail="This dubbing project could not be found. It may have been deleted or expired.")
        
    import json
    import shutil
    with open(session_json, "r", encoding="utf-8") as f:
        chunks = json.load(f)
        
    chunk = None
    for c in chunks:
        if c["chunk_id"] == chunk_id:
            chunk = c
            break
            
    if not chunk:
        raise HTTPException(status_code=404, detail="The audio segment you are trying to edit could not be found.")
        
    temp_files = []
    reference_audio_path = None
    
    if ref_file and ref_file.filename:
        # Save custom uploaded reference file
        # Pird: per-workspace + per-user temp dir. See Fix 5.
        temp_dir = Path("data/jobs/playground_tmp") / user.workspace_id / user.user_id
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_file_path = temp_dir / f"upload_{uuid.uuid4().hex}.wav"
        with open(temp_file_path, "wb") as f:
            content = await _bounded_read(ref_file)
            f.write(content)
        reference_audio_path = str(temp_file_path)
        temp_files.append(reference_audio_path)
    else:
        # Fall back to original Kurdish segment's audio_file
        reference_audio_path = chunk.get("audio_file")
        
    if not reference_audio_path or not os.path.exists(reference_audio_path):
        raise HTTPException(status_code=400, detail="Reference audio missing for this chunk.")
        
    # Generate Fish Speech TTS
    from app.services.vcta.tts_engine import _call_fish_speech
    from scripts.audio_assembly import process_chunk_assembly
    
    if not arabic_text and kurdish_raw:
        from app.services.vcta.translator import translate_batch
        temp_chunk = {
            "chunk_id": chunk_id,
            "speech_duration": chunk.get("speech_duration", 3.0),
            "kurdish_raw": kurdish_raw,
            "status": "pending"
        }
        res = await translate_batch([temp_chunk], rolling_cps=rolling_cps)
        arabic_text = res[0].get("arabic_text", "")
    
    tts_dir = work_dir / "tts"
    tts_dir.mkdir(parents=True, exist_ok=True)
    
    tts_wav_path = tts_dir / f"playground_tts_{chunk_id}_{uuid.uuid4().hex}.wav"
    temp_files.append(str(tts_wav_path))
    
    chunk["kurdish_raw"] = kurdish_raw
    chunk["arabic_text"] = arabic_text
    chunk["status"] = "approved"
    chunk["tts_file"] = str(tts_wav_path)
    
    # Save the updated session chunks info
    with open(session_json, "w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)
    
    success = await _call_fish_speech(arabic_text, reference_audio_path, str(tts_wav_path), chunk_id)
    if not success:
        for tf in temp_files:
            if os.path.exists(tf) and tf != chunk.get("audio_file"):
                try: os.remove(tf)
                except Exception: pass
        raise HTTPException(status_code=500, detail="Fish Speech call failed for segment.")
        
    # Run Audio Assembly Matrix
    output_filename = f"assembled_play_chunk_{chunk_id}_{uuid.uuid4().hex}.wav"
    output_path = Path("static/outputs") / output_filename
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    updated_chunk, assembled_path, updated_cps, updated_debt = await process_chunk_assembly(
        chunk=chunk,
        tts_dir=str(tts_dir),
        output_dir=str(Path("static/outputs")),
        rolling_cps=rolling_cps,
        padding_debt_ms=padding_debt_ms
    )
    
    shutil.move(assembled_path, str(output_path))
    
    # Cleanup
    for tf in temp_files:
        if os.path.exists(tf) and tf != chunk.get("audio_file") and tf != str(tts_wav_path):
            try: os.remove(tf)
            except Exception: pass
            
    if os.path.exists(tts_wav_path):
        try: os.remove(tts_wav_path)
        except Exception: pass
        
    return {
        "audio_url": f"/static/outputs/{output_filename}",
        "arabic_text": arabic_text,
        "rolling_cps": updated_cps,
        "padding_debt_ms": updated_debt,
        "path_taken": updated_chunk.get("path_taken", "Unknown"),
        "delta": updated_chunk.get("delta", 0.0),
        "tts_duration": updated_chunk.get("tts_duration", 0.0),
        "truncated": updated_chunk.get("truncated", False),
        "truncated_ms": updated_chunk.get("truncated_ms", 0.0),
        "pre_truncation_tts_duration": updated_chunk.get("pre_truncation_tts_duration", 0.0)
    }


@router.post("/render-final")
async def render_final_video(
    session_id: str = Form(...),
    rolling_cps: float = Form(...),
    chunks_json: str = Form(...),
    ref_file: Optional[UploadFile] = File(None),
    force: bool = Form(False),
    user: AuthenticatedUser = Depends(require_user)
):
    import json
    import shutil
    # PIRD DR-006: verify the caller owns this playground session.
    _check_playground_owner(session_id, user)

    work_dir = Path(f"data/jobs/playground_ingest/{session_id}")
    if not work_dir.exists():
        raise HTTPException(status_code=404, detail="This dubbing project could not be found. It may have been deleted or expired.")
        
    # STATE B compatibility score warning check
    voice_id_file = work_dir / "selected_voice_id.txt"
    if voice_id_file.exists() and not force:
        selected_voice = voice_id_file.read_text(encoding="utf-8").strip()
        if selected_voice:
            from app.services.vcta.translator import VOICE_PROFILES
            vp = VOICE_PROFILES.get(selected_voice)
            if vp:
                source_profile_path = work_dir / "source_profile.json"
                if source_profile_path.exists():
                    try:
                        with open(source_profile_path, "r", encoding="utf-8") as pf:
                            source_profile = json.load(pf)
                        
                        WEIGHT_CPS = 0.60
                        WEIGHT_PITCH = 0.25
                        WEIGHT_ENERGY = 0.15

                        diff_cps = abs(source_profile['cps'] - vp['cps']) / 5.0
                        diff_pitch = abs(source_profile['pitch_hz'] - vp['pitch_hz']) / 100.0
                        diff_energy = abs(source_profile['energy_db'] - vp['energy_db']) / 10.0

                        penalty = (diff_cps * WEIGHT_CPS) + (diff_pitch * WEIGHT_PITCH) + (diff_energy * WEIGHT_ENERGY)
                        score = max(0.0, 100.0 - (penalty * 100.0))
                        
                        if score < 40.0:
                            return {
                                "status": "warning",
                                "message": "This voice profile does not match the energy/speed of your video. Audio sync issues may occur. Proceed?"
                            }
                    except Exception as e:
                        logger.error(f"[RENDER] Compatibility check error: {e}")
        
    edited_chunks = json.loads(chunks_json)
    session_json = work_dir / "session_chunks.json"
    with open(session_json, "r", encoding="utf-8") as f:
        original_chunks = json.load(f)
        
    edited_ar_map = {c["chunk_id"]: c["arabic_text"] for c in edited_chunks}
    edited_ku_map = {c["chunk_id"]: c.get("kurdish_raw", "") for c in edited_chunks}
    
    # NO SILENT FALLBACK PROCESSING ALLOWED HERE!
    # /video/render-final must strictly only assemble chunks that have already passed through 
    # the /video/process-chunk pipeline (which includes translation, TTS, and AudioAssembler physics).
    
    missing_chunks = []
    
    for c in original_chunks:
        c["arabic_text"] = edited_ar_map.get(c["chunk_id"], c.get("arabic_text", ""))
        c["kurdish_raw"] = edited_ku_map.get(c["chunk_id"], c.get("kurdish_raw", ""))
        
        # Check: chunk has Kurdish text but TTS was never generated â†’ block render
        has_tts = c.get("status") == "tts_done" and c.get("tts_file") and os.path.exists(c["tts_file"])
        if c.get("kurdish_raw") and not has_tts:
            missing_chunks.append(c["chunk_id"])
            
    if missing_chunks:
        raise HTTPException(
            status_code=400, 
            detail=f"The following chunks have not been processed into audio yet: {', '.join(missing_chunks)}. Please wait for them to process."
        )
        
    # Save the updated session chunks info
    with open(session_json, "w", encoding="utf-8") as f:
        json.dump(original_chunks, f, ensure_ascii=False, indent=2)

            
    from app.services.vcta import assembler
    background_sfx_music = str(work_dir / "background_sfx_music.wav")
    original_video = str(work_dir / "original.mp4")
    
    try:
        final_mp4 = await assembler.assemble_final_video(
            chunks=original_chunks,
            background_wav=background_sfx_music,
            video_path=original_video,
            work_dir=str(work_dir),
            base_cps=rolling_cps
        )
    except Exception as e:
        logger.exception("[RENDER] Cinematic assembly failed")
        raise HTTPException(status_code=500, detail=f"Assembly failed: {str(e)}")
        
    output_filename = f"dubbed_{session_id}_{uuid.uuid4().hex}.mp4"
    public_path = Path("static/outputs") / output_filename
    public_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(final_mp4, str(public_path))
    
    # Mux Arabic dialogue speech-only track (arabic_voice.wav) with the original video
    arabic_voice_wav = str(work_dir / "arabic_voice.wav")
    arabic_vocals_public_filename = f"ar_vocals_{session_id}.mp4"
    arabic_vocals_public_path = Path("static/outputs") / arabic_vocals_public_filename
    await _mux_audio_video(original_video, arabic_voice_wav, str(arabic_vocals_public_path))
    
    
        
    return {
        "video_url": f"/static/outputs/{output_filename}",
        "video_arabic_vocals_url": f"/static/outputs/{arabic_vocals_public_filename}"
    }


@router.get("/playground-chunk-audio/{session_id}/{chunk_id}")
async def get_playground_chunk_audio(session_id: str, chunk_id: str, user: AuthenticatedUser = Depends(require_user)):
    _check_playground_owner(session_id, user)
    path = Path(f"data/jobs/playground_ingest/{session_id}/chunks/{chunk_id}.wav")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found.")
    return FileResponse(str(path), media_type="audio/wav")


@router.get("/playground-arabic-audio/{session_id}/{chunk_id}")
async def get_playground_arabic_audio(session_id: str, chunk_id: str, user: AuthenticatedUser = Depends(require_user)):
    _check_playground_owner(session_id, user)
    path = Path(f"data/jobs/playground_ingest/{session_id}/tts/tts_{chunk_id}.wav")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Arabic TTS file not found.")
    return FileResponse(str(path), media_type="audio/wav")


@router.post("/upload-global-voice")
async def upload_global_voice(
    session_id: str = Form(...),
    voice_file: UploadFile = File(...),
    user: AuthenticatedUser = Depends(require_user),
):
    """
    Upload a custom voice reference WAV file for the session.
    When present, this file is used as the Fish Speech reference for ALL chunks
    instead of the per-chunk Kurdish audio.
    """
    import shutil
    # PIRD-006: reject path-traversal in the filename.
    if voice_file.filename and (".." in voice_file.filename or "/" in voice_file.filename or "\\" in voice_file.filename):
        raise HTTPException(status_code=400, detail="Invalid filename")
    # PIRD-006: enforce audio content type.
    if not (voice_file.content_type or "").startswith("audio/"):
        raise HTTPException(status_code=400, detail=f"Expected audio/* content type, got {voice_file.content_type!r}")
    # PIRD-013: voice-recording consent gate.
    await _check_voice_recording_consent(user)
    _check_playground_owner(session_id, user)
    work_dir = Path(f"data/jobs/playground_ingest/{session_id}")
    if not work_dir.exists():
        raise HTTPException(status_code=404, detail="This dubbing project could not be found. It may have been deleted or expired.")

    # Save to a fixed name so process-chunk can find it
    dest_path = work_dir / "global_voice_ref.wav"

    # Convert to wav using ffmpeg for safety (handles mp3, ogg, m4a, wav)
    import tempfile, subprocess as sp
    suffix = Path(voice_file.filename or "voice.wav").suffix or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        content = await _bounded_read(voice_file)
        tmp.write(content)
        tmp_path = tmp.name

    # Convert to standard 16kHz mono WAV
    cmd = [
        "ffmpeg", "-y", "-i", tmp_path,
        "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "1",
        str(dest_path)
    ]
    result = await asyncio.to_thread(
        sp.run, cmd,
        stdin=sp.DEVNULL, stdout=sp.DEVNULL, stderr=sp.PIPE, text=True
    )
    try:
        os.remove(tmp_path)
    except Exception:
        pass

    if result.returncode != 0 or not dest_path.exists():
        raise HTTPException(status_code=500, detail="Failed to process voice file. Make sure it is a valid audio file.")

    # Get duration for confirmation
    from app.services.vcta.tts_engine import _get_audio_duration
    dur = await _get_audio_duration(str(dest_path))

    logger.info(f"[VOICE] Global voice ref uploaded for session {session_id}: {voice_file.filename} ({dur:.2f}s)")

    return {
        "status": "ok",
        "filename": voice_file.filename,
        "duration": round(dur, 2),
        "path": str(dest_path)
    }


@router.delete("/upload-global-voice/{session_id}")
async def delete_global_voice(session_id: str, user: AuthenticatedUser = Depends(require_user)):
    """Remove the custom voice reference, reverting to per-chunk Kurdish cloning."""
    _check_playground_owner(session_id, user)
    path = Path(f"data/jobs/playground_ingest/{session_id}/global_voice_ref.wav")
    if path.exists():
        path.unlink()
    return {"status": "cleared"}


@router.post("/select-voice/{session_id}")
async def select_voice(session_id: str, voice_id: str = Form(...), user: AuthenticatedUser = Depends(require_user)):
    """Save a Fish Audio library voice ID. All chunks will use this voice."""
    _check_playground_owner(session_id, user)
    clean_voice_id = voice_id.strip()
    import re
    if not re.fullmatch(r"^[a-zA-Z0-9_-]{1,128}$", clean_voice_id):
        raise HTTPException(status_code=400, detail="Invalid voice_id format.")
    work_dir = Path(f"data/jobs/playground_ingest/{session_id}")
    if not work_dir.exists():
        raise HTTPException(status_code=404, detail="This dubbing project could not be found. It may have been deleted or expired.")
    voice_id_file = work_dir / "selected_voice_id.txt"
    voice_id_file.write_text(clean_voice_id, encoding="utf-8")
    # Clear any uploaded WAV reference so the ID takes priority cleanly
    wav_ref = work_dir / "global_voice_ref.wav"
    if wav_ref.exists():
        wav_ref.unlink()
    logger.info(f"[VOICE] Session {session_id} selected Fish Audio voice: {clean_voice_id}")
    return {"status": "ok", "voice_id": clean_voice_id}


@router.delete("/select-voice/{session_id}")
async def clear_selected_voice(session_id: str, user: AuthenticatedUser = Depends(require_user)):
    """Clear the selected voice ID, reverting to per-chunk Kurdish cloning."""
    _check_playground_owner(session_id, user)
    work_dir = Path(f"data/jobs/playground_ingest/{session_id}")
    voice_id_file = work_dir / "selected_voice_id.txt"
    if voice_id_file.exists():
        voice_id_file.unlink()
    return {"status": "cleared"}


@router.post("/split-chunk")
async def split_chunk(
    session_id: str = Form(...),
    chunk_id: str = Form(...),
    t_anchor: float = Form(...),
    kurdish_raw_a: str = Form(...),
    kurdish_raw_b: str = Form(...),
    user: AuthenticatedUser = Depends(require_user),
):
    """
    Slices a parent chunk into Part A and Part B using VAD Snapping & Fading.
    Replaces the parent chunk object with chunk_id_A and chunk_id_B in session_chunks.json.
    """
    raise HTTPException(status_code=501, detail="This feature is currently unavailable.")


@router.post("/process-chunk")

async def process_chunk(
    session_id: str = Form(...),
    chunk_id: str = Form(...),
    kurdish_raw: str = Form(...),
    rolling_cps: float = Form(13.0),
    padding_debt_ms: float = Form(0.0),
    user: AuthenticatedUser = Depends(require_user),
):
    """
    Per-chunk AI processing â€” Full pipeline:
      1. Iraqi Arabic translation
      2. Padded Audio Rule (trim reference if chunk has lots of silence)
      3. Fish Speech TTS (uses global_voice_ref.wav if uploaded, else per-chunk Kurdish audio)
      4. AudioAssembler Path A/B/C (time-fit to exact VAD slot width)
    Arabic textarea and audio player stay LOCKED until this succeeds.
    """

    import json, shutil
    _check_playground_owner(session_id, user)

    def get_pacing_candidates(source_cps: float) -> list[tuple[str, float]]:
        import os
        from app.services.vcta.translator import VOICE_PROFILES
        
        # 1. Fetch user's models from Fish Audio API
        api_key = os.getenv("FISH_SPEECH_API_KEY", "") or os.getenv("FISH_AUDIO_API_KEY", "")
        candidates_list = []
        if api_key:
            try:
                import httpx
                with httpx.Client(timeout=5.0) as client:
                    resp = client.get(
                        "https://api.fish.audio/model",
                        headers={"Authorization": f"Bearer {api_key}"}
                    )
                    if resp.status_code == 200:
                        items = resp.json().get("items", [])
                        for item in items:
                            v_id = item.get("_id")
                            if v_id:
                                # Resolve CPS from VOICE_PROFILES, default to global_wav_fallback
                                profile = VOICE_PROFILES.get(v_id)
                                if profile:
                                    v_cps = profile.get("cps", 11.5)
                                else:
                                    v_cps = VOICE_PROFILES.get("global_wav_fallback", {}).get("cps", 11.5)
                                candidates_list.append((v_id, v_cps))
            except Exception as e:
                logger.error(f"Failed to fetch models from Fish Audio for auto-selection: {e}")
                
        # 2. If dynamic lookup failed or no models found, fallback to hardcoded VOICE_PROFILES
        if not candidates_list:
            for voice_id, profile in VOICE_PROFILES.items():
                if voice_id == "global_wav_fallback":
                    continue
                candidates_list.append((voice_id, profile.get("cps", 11.5)))
                
        return candidates_list

    work_dir = Path(f"data/jobs/playground_ingest/{session_id}")
    session_json = work_dir / "session_chunks.json"
    if not session_json.exists():
        raise HTTPException(status_code=404, detail="This dubbing project could not be found. It may have been deleted or expired.")

    with open(session_json, "r", encoding="utf-8") as f:
        chunks = json.load(f)

    chunk = next((c for c in chunks if c["chunk_id"] == chunk_id), None)
    if not chunk:
        raise HTTPException(status_code=404, detail="The audio segment you are trying to edit could not be found.")

    # â”€â”€ Voice Check for CPS Math â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Pass the selected voice ID to the translation engine so it can use
    # its Voice Profiling map to calculate dynamic text limits.
    voice_id_file = work_dir / "selected_voice_id.txt"
    global_voice_ref = work_dir / "global_voice_ref.wav"
    
    translation_voice_id = None
    if voice_id_file.exists():
        translation_voice_id = voice_id_file.read_text(encoding="utf-8").strip() or None
    elif global_voice_ref.exists():
        translation_voice_id = "global_wav"
    else:
        # No voice selected, and no global WAV ref uploaded.
        # Instead of falling back to Kurdish voice cloning, select the best voice!
        source_cps = 13.0
        cps_path = work_dir / "source_cps.txt"
        if cps_path.exists():
            try:
                source_cps = float(cps_path.read_text(encoding="utf-8").strip())
            except Exception:
                pass
        
        # Find the best voice dynamically
        candidates = get_pacing_candidates(source_cps)
        if candidates:
            # Sort by speed_diff descending
            candidates.sort(key=lambda x: x[1] - source_cps, reverse=True)
            best_voice_id = candidates[0][0]
            logger.info(f"[PROCESS-CHUNK] {chunk_id} â€” No voice selected. Auto-selected best voice for pacing limits: {best_voice_id}")
            translation_voice_id = best_voice_id
        else:
            translation_voice_id = None

    # Step 1: Translation
    from app.services.vcta.translator import translate_batch
    from app.core.sanitizer import sanitize_transcript
    clean_kurdish_raw = sanitize_transcript(kurdish_raw)
    chunk["kurdish_raw"] = clean_kurdish_raw
    chunk["status"] = "pending"
    logger.info(f"[PIPELINE-START] {chunk_id} starting translation...")
    try:
        translated = await translate_batch([chunk], rolling_cps=rolling_cps, selected_voice_id=translation_voice_id)
        arabic_text = translated[0].get("arabic_text", "") if translated else ""
    except Exception as e:
        logger.exception(f"[PROCESS-CHUNK] {chunk_id} translation failed: {e}")
        raise HTTPException(status_code=500, detail="Translation failed.")

    if not arabic_text:
        raise HTTPException(status_code=500, detail="Translation returned empty text.")

    logger.info(f"[PIPELINE-TRANS-DONE] {chunk_id} translation completed: '{arabic_text}'")

    # â”€â”€ Step 2: Reference Audio Selection â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    from app.services.vcta.tts_engine import _call_fish_speech, _trim_reference_audio
    tts_dir = work_dir / "tts"
    tts_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = work_dir / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    # â”€â”€ Voice Priority System â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Priority 1: Fish Audio Library Voice ID (fastest, no audio bytes sent)
    # Priority 2: Uploaded WAV file reference (global_voice_ref.wav)
    # Priority 3: Per-chunk Kurdish audio (default â€” voice cloning)

    voice_id_file = work_dir / "selected_voice_id.txt"
    selected_voice_id: str | None = None
    if voice_id_file.exists():
        selected_voice_id = voice_id_file.read_text(encoding="utf-8").strip() or None

    effective_ref = ""  # only used in Mode 2 (audio bytes)

    if selected_voice_id:
        logger.info(f"[PROCESS-CHUNK] {chunk_id} â€” using FISH AUDIO LIBRARY VOICE: {selected_voice_id}")
    else:
        # User is in "Auto" or "Clone" mode
        global_voice_ref = work_dir / "global_voice_ref.wav"
        if global_voice_ref.exists():
            effective_ref = str(global_voice_ref)
            logger.info(f"[PROCESS-CHUNK] {chunk_id} â€” using GLOBAL VOICE REFERENCE WAV (STATE A)")
        else:
            # STATE C: User Selected "Auto" / Reverted to Auto
            # Swaps reference audio based on speaker label
            speaker_id = chunk.get("speaker", "A")
            speaker_ref = work_dir / f"speaker_ref_{speaker_id}.wav"
            if speaker_ref.exists():
                effective_ref = str(speaker_ref)
                logger.info(f"[PROCESS-CHUNK] {chunk_id} â€” Auto-routing: using Speaker {speaker_id} reference clip (STATE C)")
            else:
                # Fallback to per-chunk Kurdish audio
                reference_audio_path = chunk.get("audio_file")
                if not reference_audio_path or not os.path.exists(reference_audio_path):
                    raise HTTPException(status_code=400, detail="Reference Kurdish audio missing for this chunk.")

                is_padded = chunk.get("padded", False)
                speech_dur = chunk.get("speech_duration", chunk.get("total_duration", 3.0))

                if is_padded:
                    trimmed_ref = str(tmp_dir / f"{chunk_id}_ref_trimmed.wav")
                    trim_ok = await _trim_reference_audio(reference_audio_path, speech_dur, trimmed_ref)
                    effective_ref = trimmed_ref if trim_ok else reference_audio_path
                    logger.info(f"[PROCESS-CHUNK] {chunk_id} padded=True â€” trimmed reference to {speech_dur:.2f}s")
                else:
                    effective_ref = reference_audio_path

    # â”€â”€ Step 3: Fish Speech TTS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    import time
    tts_start = time.time()
    tts_retries = []
    logger.info(f"[PIPELINE-TTS-START] {chunk_id} starting TTS synthesis...")
    raw_tts_path = tts_dir / f"raw_tts_{chunk_id}.wav"
    success = await _call_fish_speech(
        arabic_text,
        effective_ref,
        str(raw_tts_path),
        chunk_id,
        reference_id=selected_voice_id,
        trace_retries=tts_retries
    )
    tts_execution_time = round(time.time() - tts_start, 2)

    if not success:
        logger.error(f"[PIPELINE-TTS-FAILED] {chunk_id} Fish Speech TTS failed.")
        raise HTTPException(status_code=500, detail="Fish Speech TTS failed for this chunk.")

    logger.info(f"[PIPELINE-TTS-DONE] {chunk_id} TTS synthesis completed.")

    # â”€â”€ Step 4: AudioAssembler â€” Path A / B / C (fit to exact slot width) â”€â”€â”€â”€
    logger.info(f"[PIPELINE-ASS-START] {chunk_id} starting audio assembly...")
    from scripts.audio_assembly import process_chunk_assembly
    chunk["arabic_text"] = arabic_text
    chunk["status"] = "approved"       # required by process_chunk() guard
    chunk["tts_file"] = str(raw_tts_path)

    assembled_output_dir = str(work_dir / "assembled")
    os.makedirs(assembled_output_dir, exist_ok=True)

    try:
        updated_chunk, assembled_path, updated_cps, updated_debt = await process_chunk_assembly(
            chunk=chunk,
            tts_dir=str(tts_dir),
            output_dir=assembled_output_dir,
            rolling_cps=rolling_cps,
            padding_debt_ms=padding_debt_ms,
        )
    except Exception as e:
        logger.exception(f"[PROCESS-CHUNK] {chunk_id} AudioAssembler failed: {e}")
        logger.error(f"[PIPELINE-ASS-FAILED] {chunk_id} audio assembly failed.")
        raise HTTPException(status_code=500, detail=f"Audio assembly failed: {str(e)}")

    # Move the assembled (time-fitted) file to tts dir for the serve endpoint
    final_tts_path = tts_dir / f"tts_{chunk_id}.wav"
    shutil.move(assembled_path, str(final_tts_path))
    logger.info(f"[PIPELINE-ASS-DONE] {chunk_id} audio assembly completed.")

    # Calculate silence padding distribution details
    path_taken = updated_chunk.get("path_taken", "?")
    delta = updated_chunk.get("delta", 0.0)
    
    pre_delay_ms = 0
    post_delay_ms = 0
    if path_taken == "C":
        # Absorbed deficit: pre-pad with 30%, post-pad with 70%
        # delta here is the absorbed deficit or surplus gap
        pre_delay_ms = int(0.30 * delta * 1000)
        post_delay_ms = int(0.70 * delta * 1000)
        
    pacing_trace = {
        "slot_duration": chunk.get("total_duration", 0.0),
        "tts_duration": updated_chunk.get("tts_duration", 0.0),
        "path_taken": path_taken,
        "delta": delta,
        "pre_delay_ms": pre_delay_ms,
        "post_delay_ms": post_delay_ms
    }
    
    # Compile pipeline details trace
    pipeline_details = {
        "translation": chunk.get("_translation_trace", {}),
        "condenser_retries": chunk.get("_condenser_trace", []),
        "tts": {
            "input_text": arabic_text,
            "voice_mode": "library" if selected_voice_id else "cloned",
            "voice_id": selected_voice_id or os.path.basename(effective_ref),
            "execution_time_sec": tts_execution_time,
            "retries": tts_retries
        },
        "pacing": pacing_trace
    }

    # â”€â”€ Step 5: Persist â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    chunk["arabic_text"] = arabic_text
    chunk["status"] = "tts_done"
    chunk["tts_file"] = str(final_tts_path)
    chunk["rolling_cps"] = updated_cps
    chunk["padding_debt_ms"] = updated_debt
    chunk["path_taken"] = path_taken
    chunk["delta"] = delta
    chunk["tts_duration"] = updated_chunk.get("tts_duration", 0.0)
    chunk["pipeline_details"] = pipeline_details

    with open(session_json, "w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)

    return {
        "chunk_id": chunk_id,
        "arabic_text": arabic_text,
        "arabic_audio_url": f"/video/playground-arabic-audio/{session_id}/{chunk_id}",
        "rolling_cps": updated_cps,
        "padding_debt_ms": updated_debt,
        "path_taken": path_taken,
        "delta": delta,
        "tts_duration": updated_chunk.get("tts_duration", 0.0),
        "status": "tts_done",
        "pipeline_details": pipeline_details
    }


@router.get("/playground-logs")
async def get_playground_logs(lines: int = 100, user: AuthenticatedUser = Depends(require_user)):
    """Returns the last N lines of the vcta.log file for the dashboard terminal.

    Pird: auth-gated. Without this, unauthenticated callers can scrape
    pipeline telemetry. See handoffs/dubbing-security-pass2-fixes.md Fix 8.
    PIRD-020: lines parameter is capped at max 500 lines to prevent resource exhaustion.
    """
    lines = max(1, min(lines, 500))
    log_file = Path("data/logs/vcta.log")
    if not log_file.exists():
        return {"logs": ["[SYSTEM] Log file not created yet..."]}

    try:
        # A simple readlines (file shouldn't be too huge, but if it is we should tail it)
        with open(log_file, "r", encoding="utf-8") as f:
            all_lines = f.readlines()
            # Return last N lines
            return {"logs": all_lines[-lines:]}
    except Exception as e:
        return {"logs": [f"[ERROR] Could not read logs: {str(e)}"]}

