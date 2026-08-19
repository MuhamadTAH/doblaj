"""
Internal dubbing job endpoint — no Supabase auth, gated only by
INTERNAL_API_KEY shared with peer services (bot-bridge, ai-gateway).

Accepts a multipart video upload from an internal caller, returns a
job_id immediately, runs a mock 2-second "processing" pass via FastAPI
BackgroundTasks, then POSTs {job_id, video_url, chat_id} to the caller-
supplied webhook_url.

This is the MOCK round-trip path. The real Celery-backed pipeline lives
in app/api/routes/video.py and is gated by Supabase JWT (require_user).
To swap to real processing later, replace `_mock_process_and_callback`
with a call to worker_process_video_job.
"""
import ipaddress
import os
import re
import socket
import uuid
import json
import asyncio
import hmac
import logging
from pathlib import Path

import httpx

from fastapi import APIRouter, UploadFile, File, Form, Header, HTTPException, BackgroundTasks, Request
from pydantic import BaseModel
from typing import Optional

# PIRD-010: shared per-IP limiter (see app/core/ratelimit.py).
from app.core.ratelimit import rate_limited as _rate_limited

logger = logging.getLogger(__name__)
router = APIRouter()


# Part04 / Layer 2: per-field validation for the multipart Form fields
# on `create_internal_job`. Same reasoning as `video.py`:
# `_validate_form_field` — payload-bloat, log-injection, abuse.
_FIELD_CONSTRAINTS = {
    "chat_id":     {"max_length": 128, "no_control_chars": True},
    "source":      {"max_length": 32,  "no_control_chars": True},
    "webhook_url": {"max_length": 2048, "no_control_chars": True},
}


def _validate_form_field(name: str, value: Optional[str]) -> None:
    """Part04 / Layer 2: tighten free-form Form fields on the internal
    job route. `webhook_url` is also SSRF-pinned by `_resolve_pinned_ip`;
    the length cap is independent defense against oversized payloads."""
    if value is None:
        return
    if not isinstance(value, str):
        raise HTTPException(status_code=400, detail=f"{name}: must be a string")
    spec = _FIELD_CONSTRAINTS.get(name)
    if spec is None:
        return
    if len(value) > spec["max_length"]:
        raise HTTPException(
            status_code=400,
            detail=f"{name}: max length {spec['max_length']} characters",
        )
    if spec.get("no_control_chars") and any(ord(c) < 0x20 or ord(c) == 0x7f for c in value):
        raise HTTPException(
            status_code=400,
            detail=f"{name}: control characters are not allowed",
        )
    if "pattern" in spec and not re.fullmatch(spec["pattern"], value):
        raise HTTPException(
            status_code=400,
            detail=f"{name}: invalid format",
        )

INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")

# PIRD-004: explicit cloud-metadata and link-local blocklist. Even
# though ipaddress considers these `is_private` / `is_link_local`,
# listing them explicitly makes the intent visible and survives any
# future Python stdlib reclassification.
_CLOUD_METADATA_IPS = {
    "169.254.169.254",       # AWS / GCP / Azure IMDS
    "fd00:ec2::254",         # AWS IMDSv2 IPv6
    "169.254.170.2",         # AWS ECS task metadata
    "100.100.100.200",       # Alibaba / generic metadata
}

# PIRD-004: optional CIDR allowlist for the webhook target. When set,
# the resolved IP must be inside one of these CIDRs. Default = unset
# (no allowlist enforced).
def _parse_allowlist() -> list:
    raw = os.getenv("INTERNAL_JOB_WEBHOOK_IP_ALLOWLIST", "").strip()
    if not raw:
        return []
    out = []
    for cidr in raw.split(","):
        cidr = cidr.strip()
        if not cidr:
            continue
        try:
            out.append(ipaddress.ip_network(cidr, strict=False))
        except ValueError as e:
            logger.warning(f"[INTERNAL-JOB] invalid CIDR in allowlist {cidr!r}: {e}")
    return out


_WEBHOOK_IP_ALLOWLIST = _parse_allowlist()

# ponytail: pick a small .mp4 (350KB chunk) as the mock deliverable.
# Smaller = more reliable re-upload over the flaky api.telegram.org
# connection. Real impl will set this to the actual rendered file.
_MOCK_OUTPUT = (
    Path(__file__).resolve().parents[3]
    / "static"
    / "outputs"
    / "video_chunk_job_8370e189_6.mp4"
)


class InternalJobCreateResponse(BaseModel):
    id: str
    status: str
    webhook_url: Optional[str] = None
    chat_id: Optional[str] = None


class InternalJobStatusResponse(BaseModel):
    id: str
    status: str  # pending | processing | completed | failed
    progress: int
    video_url: Optional[str] = None
    error: Optional[str] = None


# ponytail: in-memory job store. One process, no Redis needed for the
# mock path. Real impl writes to Supabase app.dubbing_jobs.
_JOB_STORE: dict[str, dict] = {}


def _check_internal_key(x_internal_key: Optional[str]) -> None:
    if not INTERNAL_API_KEY:
        raise HTTPException(status_code=503, detail="INTERNAL_API_KEY not configured on server")
    # Pird: constant-time comparison. `!=` is timing-leaky. See
    # handoffs/dubbing-security-pass2-fixes.md Fix 10.
    if not hmac.compare_digest(x_internal_key or "", INTERNAL_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid x-internal-key")


@router.post("/internal/jobs", response_model=InternalJobCreateResponse)
# PIRD-010: per-IP rate limit on internal job creation. The comment used to
# sit here without a decorator below it, so this route was never limited.
@_rate_limited("5/minute")
async def create_internal_job(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    webhook_url: Optional[str] = Form(None),
    chat_id: Optional[str] = Form(None),
    source: Optional[str] = Form("telegram"),  # ponytail: for logs only
    x_internal_key: Optional[str] = Header(None),
):
    """
    Internal-only entry. No Supabase JWT check.

    Body (multipart/form-data):
      file: video file
      webhook_url: optional URL to POST {job_id, video_url, chat_id} to on completion
      chat_id: optional caller-side ID (e.g. Telegram chat id) echoed back in the callback
      source: optional label, e.g. "telegram" or "chatwoot"

    Returns 202 with job_id. Caller can poll /video/internal/jobs/{id}/status
    OR wait for the webhook.
    """
    _check_internal_key(x_internal_key)
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    # Part04 / Layer 2: validate free-form Form fields before any
    # downstream write or log line consumes them. `webhook_url` is also
    # SSRF-pinned by `_resolve_pinned_ip` later — the length cap here
    # is independent defense against oversized payloads.
    _validate_form_field("chat_id", chat_id)
    _validate_form_field("source", source)
    _validate_form_field("webhook_url", webhook_url)

    job_id = uuid.uuid4().hex

    # Save upload under data/uploads/internal/<job_id>.<ext> so it can be
    # served back via /static if a caller wants it.
    upload_dir = Path("data/uploads/internal")
    upload_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(file.filename).suffix or ".mp4"
    saved_path = upload_dir / f"{job_id}{ext}"
    # Pird: bounded read so a 5 GB POST doesn't OOM the worker. See
    # handoffs/dubbing-security-pass2-fixes.md Fix 9.
    _max = int(os.getenv("INTERNAL_JOB_MAX_BYTES", str(1024 * 1024 * 1024)))
    chunks: list[bytes] = []
    total = 0
    while True:
        c = await file.read(64 * 1024)
        if not c:
            break
        total += len(c)
        if total > _max:
            raise HTTPException(status_code=413, detail=f"Upload exceeds {_max} bytes")
        chunks.append(c)
    saved_path.write_bytes(b"".join(chunks))
    content = b"".join(chunks)
    del chunks

    # 1. Resolve workspace_id from chat_id
    workspace_id = os.getenv("BOT_SERVICE_WORKSPACE_ID", "telegram-bot-ws")
    if chat_id:
        try:
            from app.core import database as sql_db
            linked_ws = await sql_db.get_workspace_by_telegram_id(chat_id)
            if linked_ws:
                workspace_id = linked_ws
        except Exception as e:
            logger.warning(f"Error looking up workspace for chat_id {chat_id}: {e}")

    # 2. Upload source video to Cloudflare R2 if available
    source_r2_key = ""
    from app.services import r2
    if r2.R2_ENDPOINT:
        try:
            source_r2_key = r2.dubbing_key(workspace_id, job_id, f"source{ext}")
            logger.info(f"[INTERNAL-JOB] Uploading input video to R2: {source_r2_key}")
            await asyncio.to_thread(r2.upload_file, source_r2_key, str(saved_path))
        except Exception as e:
            logger.error(f"[INTERNAL-JOB] Failed to upload input video to R2: {e}")

    # 3. Create real job in Convex
    try:
        from app.core import database_convex
        await database_convex.create_job(
            workspace_id=workspace_id,
            owner_user_id=f"tg_{chat_id}" if chat_id else "telegram_bot",
            job_id=job_id,
            source_video_r2_key=source_r2_key,
            consent_version="2026-07-26.1",
            user_ip_address="telegram_bot"
        )
        logger.info(f"[INTERNAL-JOB] Created real job in Convex: {job_id}")
    except Exception as e:
        logger.error(f"[INTERNAL-JOB] Failed to create job in Convex: {e}")

    # 4. Trigger local worker or MCP webhook if configured
    mcp_webhook_url = os.getenv("MCP_WEBHOOK_URL", "")
    if mcp_webhook_url:
        async def trigger_mcp():
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    await client.post(mcp_webhook_url, json={"job_id": job_id, "workspace_id": workspace_id})
                    logger.info(f"[INTERNAL-JOB] Pushed job {job_id} to MCP Webhook")
            except Exception as err:
                logger.warning(f"[INTERNAL-JOB] Failed to push to MCP webhook: {err}")
        background_tasks.add_task(trigger_mcp)

    _JOB_STORE[job_id] = {
        "status": "pending",
        "progress": 5,
        "webhook_url": webhook_url,
        "chat_id": chat_id,
        "source": source,
        "saved_path": str(saved_path),
        "workspace_id": workspace_id,
    }

    logger.info(
        "[INTERNAL-JOB] created id=%s source=%s webhook=%s chat_id=%s bytes=%d ws=%s",
        job_id, source, webhook_url, chat_id, len(content), workspace_id
    )

    return InternalJobCreateResponse(
        id=job_id,
        status="pending",
        webhook_url=webhook_url,
        chat_id=chat_id,
    )


@router.get("/internal/jobs/{job_id}/status", response_model=InternalJobStatusResponse)
async def get_internal_job_status(
    job_id: str,
    x_internal_key: Optional[str] = Header(None),
):
    _check_internal_key(x_internal_key)
    
    # 1. Query Convex for live job status
    try:
        from app.core import database_convex
        job = await database_convex.get_job(workspace_id="", job_id=job_id)
        if job:
            status = job.get("status", "pending")
            status_str = "completed" if status in ("done", "completed") else status
            base = os.getenv("DUBBING_URL", "").rstrip("/")
            video_url = f"{base}/video/internal/jobs/{job_id}/download" if status_str == "completed" else None
            return InternalJobStatusResponse(
                id=job_id,
                status=status_str,
                progress=int(job.get("progress", 0)),
                video_url=video_url,
                error=job.get("error"),
            )
    except Exception as e:
        logger.warning(f"[INTERNAL-JOB] Error querying Convex for status of {job_id}: {e}")

    # 2. Fallback to in-memory store
    job = _JOB_STORE.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    status_str = job.get("status", "pending")
    base = os.getenv("DUBBING_URL", "").rstrip("/")
    video_url = f"{base}/video/internal/jobs/{job_id}/download" if status_str == "completed" else None

    return InternalJobStatusResponse(
        id=job_id,
        status=status_str,
        progress=int(job.get("progress", 0)),
        video_url=video_url,
        error=job.get("error"),
    )


@router.get("/internal/jobs/{job_id}/download")
async def download_internal_job(
    job_id: str,
    x_internal_key: Optional[str] = Header(None),
):
    from fastapi.responses import FileResponse, RedirectResponse
    _check_internal_key(x_internal_key)
    
    output_path = ""
    try:
        from app.core import database_convex
        job = await database_convex.get_job(workspace_id="", job_id=job_id)
        if job:
            output_path = job.get("result_video_r2_key") or job.get("resultVideoR2Key") or ""
    except Exception as e:
        logger.warning(f"[INTERNAL-JOB] Error reading job from Convex for download: {e}")

    from app.services import r2
    if r2.R2_ENDPOINT and output_path and (output_path.startswith("dubbing/") or output_path.startswith("results/")):
        try:
            url = r2.signed_url(output_path, filename=f"dubbed_{job_id[:8]}.mp4", inline=False)
            return RedirectResponse(url)
        except Exception as e:
            logger.error(f"Failed to generate signed URL for R2 key {output_path}: {e}")

    if output_path and output_path.startswith("/static"):
        output_path = output_path.lstrip("/")
        
    if output_path and "data/jobs/sessions" in output_path.replace("\\", "/"):
        output_path = "data/jobs/sessions" + output_path.replace("\\", "/").split("data/jobs/sessions")[1]

    if not output_path:
        raise HTTPException(status_code=404, detail="Output file not found")

    static_root = Path("static").resolve()
    data_root = Path("data").resolve()
    try:
        resolved = Path(output_path).resolve()
    except (OSError, RuntimeError):
        raise HTTPException(status_code=404, detail="Output file not found")
        
    is_safe_path = resolved.is_relative_to(static_root) or resolved.is_relative_to(data_root)
    
    if not is_safe_path or not resolved.is_file():
        raise HTTPException(status_code=404, detail="Output file not found")

    return FileResponse(
        path=str(resolved),
        filename=resolved.name,
        media_type="video/mp4"
    )


async def _mock_process_and_callback(job_id: str) -> None:
    """
    Ponytail mock: sleep 2s, mark complete, fire callback to webhook_url.
    Replace body with real worker when ready.
    """
    job = _JOB_STORE.get(job_id)
    if not job:
        return

    try:
        # Step 1: pretend to upload
        await asyncio.sleep(0.5)
        job["progress"] = 30

        # Step 2: pretend to process
        await asyncio.sleep(1.0)
        job["progress"] = 70

        # Step 3: pretend to render
        await asyncio.sleep(0.5)
        job["progress"] = 100
        job["status"] = "completed"

        base = os.getenv("DUBBING_URL", "http://localhost:8002").rstrip("/")
        video_url = f"{base}/static/outputs/manual_job_f356502b.mp4"
        job["video_url"] = video_url

        logger.info("[INTERNAL-JOB] completed id=%s", job_id)

        webhook_url = job.get("webhook_url")
        if webhook_url:
            payload = {
                "job_id": job_id,
                "status": "completed",
                "video_url": video_url,
                "chat_id": job.get("chat_id"),
                "source": job.get("source"),
            }
            await _post_webhook(webhook_url, payload)

    except Exception as e:
        job["status"] = "failed"
        job["error"] = str(e)
        logger.exception("[INTERNAL-JOB] failed id=%s", job_id)
        webhook_url = job.get("webhook_url")
        if webhook_url:
            await _post_webhook(webhook_url, {
                "job_id": job_id,
                "status": "failed",
                "error": str(e),
                "chat_id": job.get("chat_id"),
                "source": job.get("source"),
            })


async def _post_webhook(url: str, payload: dict) -> None:
    """Fire-and-(mostly)-forget POST. ponytail: 10s timeout, log on failure."""
    # Pird: SSRF guard. webhook_url is caller-supplied and previously could
    # point at cloud metadata, local Redis, or peer services. See
    # handoffs/dubbing-audit-fixes-2026-07-15.md Fix 3.
    safe_ip = _resolve_pinned_ip(url)
    if safe_ip is None:
        logger.warning("[INTERNAL-JOB] webhook URL rejected as unsafe: %s", url)
        return
    try:
        # PIRD-004: pin the resolved IP into a custom Transport so a
        # DNS-rebinding attacker can't swap the IP between the check
        # and the actual connect.
        transport = httpx.AsyncHTTPTransport()
        async with httpx.AsyncClient(timeout=10.0, transport=transport) as client:
            # Re-construct URL with the pinned IP to bypass any
            # host-level re-resolution. We do this by passing the IP
            # in the URL and `Host` in the headers.
            from urllib.parse import urlparse, urlunparse
            p = urlparse(url)
            pinned_url = urlunparse(p._replace(netloc=f"{safe_ip}:{p.port or (443 if p.scheme == 'https' else 80)}"))
            r = await client.post(
                pinned_url,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "Host": p.hostname,
                },
            )
            logger.info(
                "[INTERNAL-JOB] webhook POST %s -> %d", url, r.status_code,
            )
    except Exception as e:
        logger.warning("[INTERNAL-JOB] webhook POST %s failed: %s", url, e)


def _resolve_pinned_ip(url: str) -> Optional[str]:
    """Return the single resolved IP for the URL's host, or None if the
    URL fails any SSRF guard. PIRD-004: rejects cloud-metadata IPs,
    private/loopback/link-local ranges, octal/hex IP forms, and
    (optionally) enforces a CIDR allowlist.
    """
    import ipaddress
    import socket
    from urllib.parse import urlparse

    if not url:
        return None
    try:
        p = urlparse(url)
    except Exception:
        return None
    is_prod = os.getenv("PIRD_ENV", "").lower() == "prod"
    if is_prod and p.scheme != "https":
        return None
    if p.scheme not in {"http", "https"}:
        return None
    if not p.hostname:
        return None

    # PIRD-004: hostname is itself a numeric IP? Reject octal/hex
    # forms. Try parsing it as a plain decimal IPv4 first.
    try:
        ip = ipaddress.ip_address(p.hostname)
        # If we got here, the "hostname" is literally an IP literal.
        # Reject loopback/private/link-local/cloud-metadata.
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or str(ip) in _CLOUD_METADATA_IPS
        ):
            return None
    except ValueError:
        # Not a literal IP — fine, we'll do a DNS lookup below.
        # But first, reject obvious octal/hex-shape hostnames
        # (`0177.0.0.1` resolves to 127.0.0.1 on some platforms).
        if re.fullmatch(r"[0-9a-fxA-FX.]+", p.hostname) and any(
            c in p.hostname for c in ("x", "X")
        ):
            return None

    # Operator hostname allowlist (matches on the URL string, not the IP).
    allow = {
        h.strip().lower()
        for h in os.getenv("INTERNAL_JOB_WEBHOOK_ALLOW", "").split(",")
        if h.strip()
    }
    if p.hostname.lower() in allow:
        logger.info(
            "[INTERNAL-JOB] webhook URL %s matched operator allowlist", p.hostname
        )

    try:
        infos = socket.getaddrinfo(
            p.hostname, p.port or (443 if p.scheme == "https" else 80)
        )
    except socket.gaierror:
        return None

    pinned: Optional[str] = None
    for family, _, _, _, sockaddr in infos:
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            return None
        if str(ip) in _CLOUD_METADATA_IPS:
            return None
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
        ):
            return None
        # If an allowlist is configured, the resolved IP MUST be inside
        # one of the configured CIDRs. If multiple IPs resolve, the
        # allowlist must allow all of them (we pin to the first; any
        # disallowed sibling means reject).
        if _WEBHOOK_IP_ALLOWLIST and not any(
            ip in net for net in _WEBHOOK_IP_ALLOWLIST
        ):
            return None
        if pinned is None:
            pinned = str(ip)
        elif pinned != str(ip):
            # Multiple distinct IPs for the same hostname — refuse to
            # pick. The caller should re-resolve.
            return None
    return pinned


# Backwards-compat alias: older code paths and tests still import
# _is_safe_webhook. Maps to the new IP-pinning check.
def _is_safe_webhook(url: str) -> bool:
    return _resolve_pinned_ip(url) is not None