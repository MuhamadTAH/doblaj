"""
pipeline_tracer.py — Pird Dubbing Pipeline Diagnostic Tracer
=============================================================

Provides per-session, step-by-step logging for every major operation in the
dubbing pipeline (transcription, translation, TTS, physics loop, assembly).

HOW IT WORKS:
  - Every pipeline function calls trace_step() to record structured events.
  - Every outbound HTTP request (OpenRouter, Fish Audio) is intercepted by
    trace_api_call() which logs: function name, model, attempt number,
    HTTP status, latency, and a short preview of the payload.
  - All events are written to:
      data/logs/pipeline/<session_id>/trace_<YYYY-MM-DD>.log
  - A single combined file is also written to:
      data/logs/pipeline_combined.log  (rotates at 20 MB)

USAGE (in any service file):
    from app.core.pipeline_tracer import trace_step, trace_api_call

    # Log a named step
    trace_step(session_id, "TRANSLATE", chunk_id="abc123",
               note="batch_translate_text", chunk_count=1)

    # Wrap an outbound HTTP call
    async with trace_api_call(session_id, "batch_translate_text",
                              model=OPENROUTER_MODEL, attempt=attempt):
        resp = await client.post(url, ...)
"""

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from logging.handlers import RotatingFileHandler
from typing import Optional

# ─────────────────────────────────────────────────────────────────────────────
# Internal logger (goes to the root handler → data/logs/vcta.log)
# ─────────────────────────────────────────────────────────────────────────────
_log = logging.getLogger("pird.tracer")

# ─────────────────────────────────────────────────────────────────────────────
# Combined rotating log (all sessions in one file for grep convenience)
# ─────────────────────────────────────────────────────────────────────────────
_COMBINED_LOG_PATH = Path("data/logs/pipeline_combined.log")
_COMBINED_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

_combined_handler = RotatingFileHandler(
    _COMBINED_LOG_PATH,
    encoding="utf-8",
    maxBytes=20 * 1024 * 1024,   # 20 MB
    backupCount=10,
)
_combined_handler.setFormatter(
    logging.Formatter("%(message)s")   # we write pre-formatted JSON lines
)
_combined_logger = logging.getLogger("pird.pipeline_combined")
_combined_logger.setLevel(logging.DEBUG)
_combined_logger.propagate = False
if not _combined_logger.handlers:
    _combined_logger.addHandler(_combined_handler)

# ─────────────────────────────────────────────────────────────────────────────
# Per-session file handler cache
# ─────────────────────────────────────────────────────────────────────────────
_session_loggers: dict[str, logging.Logger] = {}


def _get_session_logger(session_id: str) -> logging.Logger:
    """Return (or create) a file logger dedicated to this session."""
    if session_id in _session_loggers:
        return _session_loggers[session_id]

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    session_dir = Path("data/logs/pipeline") / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    log_path = session_dir / f"trace_{today}.log"

    logger = logging.getLogger(f"pird.session.{session_id}")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False   # don't double-write to root

    # Avoid adding duplicate handlers if the logger already has them
    if not logger.handlers:
        fh = logging.FileHandler(log_path, encoding="utf-8", delay=False)
        fh.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(fh)

    _session_loggers[session_id] = logger
    return logger


# ─────────────────────────────────────────────────────────────────────────────
# Public helpers
# ─────────────────────────────────────────────────────────────────────────────

def _emit(session_id: str, record: dict) -> None:
    """Serialize a record to both the session file and the combined file.
    Flushes immediately so logs survive a crash mid-job.
    """
    record.setdefault("session_id", session_id)
    record.setdefault("ts", datetime.now(timezone.utc).isoformat())

    line = json.dumps(record, ensure_ascii=False)

    sess_logger = _get_session_logger(session_id)
    sess_logger.info(line)
    # Force flush so the line is on disk even if the process crashes next
    for h in sess_logger.handlers:
        h.flush()

    _combined_logger.info(line)
    for h in _combined_logger.handlers:
        h.flush()


def trace_step(
    session_id: str,
    step: str,
    *,
    chunk_id: Optional[str] = None,
    note: Optional[str] = None,
    status: str = "START",
    **extra,
) -> None:
    """
    Record a named pipeline step event.

    Parameters
    ----------
    session_id : The session/job ID.
    step       : Human-readable step name, e.g. "TRANSCRIBE", "TRANSLATE",
                 "TTS", "PHYSICS_RETRY", "ASSEMBLE".
    chunk_id   : The chunk identifier (optional).
    note       : Free-form note.
    status     : "START" | "OK" | "FAIL" | "SKIP" | "RETRY".
    **extra    : Any extra key/value pairs to include in the log record.
    """
    record = {
        "type": "STEP",
        "step": step,
        "status": status,
    }
    if chunk_id:
        record["chunk_id"] = chunk_id
    if note:
        record["note"] = note
    record.update(extra)

    _emit(session_id, record)
    _log.debug("[%s] STEP %-20s [%s] %s %s", session_id, step, status,
               f"chunk={chunk_id}" if chunk_id else "",
               f"| {note}" if note else "")


@asynccontextmanager
async def trace_api_call(
    session_id: str,
    caller: str,
    *,
    model: Optional[str] = None,
    attempt: int = 0,
    url: str = "",
    payload_preview: Optional[dict] = None,
):
    """
    Async context manager that wraps a single outbound API call.
    Logs the start, the HTTP status, and the latency.

    Usage:
        async with trace_api_call(session_id, "batch_translate_text",
                                  model=MODEL, attempt=0) as ctx:
            resp = await client.post(url, json=payload)
            ctx["status"] = resp.status_code
    """
    ctx: dict = {"status": None, "error": None}
    start = time.monotonic()

    # Build preview from payload (capped to avoid huge logs)
    preview = {}
    if payload_preview:
        for k, v in payload_preview.items():
            if isinstance(v, str):
                preview[k] = v[:120] + ("…" if len(v) > 120 else "")
            elif isinstance(v, list):
                preview[k] = f"[{len(v)} items]"
            else:
                preview[k] = v

    _emit(session_id, {
        "type": "API_CALL_START",
        "caller": caller,
        "model": model,
        "attempt": attempt,
        "url": url,
        "payload_preview": preview,
    })

    try:
        yield ctx
    except Exception as exc:
        ctx["error"] = str(exc)
        _emit(session_id, {
            "type": "API_CALL_ERROR",
            "caller": caller,
            "model": model,
            "attempt": attempt,
            "error": str(exc),
            "latency_ms": round((time.monotonic() - start) * 1000),
        })
        raise
    finally:
        latency_ms = round((time.monotonic() - start) * 1000)
        if ctx.get("error") is None:
            _emit(session_id, {
                "type": "API_CALL_END",
                "caller": caller,
                "model": model,
                "attempt": attempt,
                "http_status": ctx.get("status"),
                "latency_ms": latency_ms,
            })
            _log.debug(
                "[%s] API %-30s attempt=%d status=%s latency=%dms",
                session_id, caller, attempt, ctx.get("status"), latency_ms,
            )


def trace_http_request_count(session_id: str, caller: str) -> None:
    """
    Lightweight single-line call counter — call once per outbound HTTP request.
    Use this in any function that already has its own try/except and doesn't
    need the full context manager overhead.
    """
    _emit(session_id, {
        "type": "HTTP_REQUEST",
        "caller": caller,
    })
    _log.debug("[%s] HTTP_REQUEST from %s", session_id, caller)


def get_session_log_path(session_id: str) -> str:
    """Return the absolute path to today's trace file for this session."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return str(
        Path("data/logs/pipeline").resolve()
        / session_id
        / f"trace_{today}.log"
    )
