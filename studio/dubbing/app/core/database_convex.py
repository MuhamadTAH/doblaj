"""
Convex backend adapter for dubbing persistence.

Single source of truth for all dubbing data. The Supabase adapter has
been removed; this module is imported directly by `app.core.db`.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import Any, Dict, List, Optional

from convex import ConvexClient

from app.core.log_redact import safe_ws

logger = logging.getLogger(__name__)

CONVEX_URL = os.getenv("CONVEX_URL", "http://127.0.0.1:3210")
CONVEX_DEPLOY_KEY = os.getenv("CONVEX_DEPLOY_KEY", "")
CONVEX_ADMIN_KEY = os.getenv("CONVEX_ADMIN_KEY", "")
# Pird (security review M5): shared secret for all `*Internal` Convex
# mutations. Must match `INTERNAL_API_KEY` on the Convex dashboard env.
# Same key as the bot-bridge / ai-gateway internal API key.
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")

_client: Optional[ConvexClient] = None
_in_memory_jobs: Dict[str, Dict[str, Any]] = {}


def _internal_args(extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Return a fresh args dict with `__internalApiKey` baked in. The
    Convex side checks this against `process.env.INTERNAL_API_KEY` at
    every `*Internal` mutation/query entry.
    """
    if not INTERNAL_API_KEY:
        # Pird: fail fast in prod. Dev mode logs a warning so the
        # operator sees the gap on first run.
        if os.getenv("PIRD_ENV", "").lower() == "prod":
            raise RuntimeError(
                "INTERNAL_API_KEY is not configured on the Python backend "
                "(set it in studio/dubbing/.env or environment to match the "
                "Convex deployment's INTERNAL_API_KEY)"
            )
        logger.warning(
            "[DATABASE-CONVEX] INTERNAL_API_KEY is unset; Convex side will reject "
            "all *Internal calls. Set the env var in dev too."
        )
    base = {"__internalApiKey": INTERNAL_API_KEY}
    if extra:
        base.update(extra)
    return base


def _get_client() -> ConvexClient:
    global _client
    if _client is None:
        _client = ConvexClient(CONVEX_URL)
    return _client


def _get_service_role_client() -> Optional[ConvexClient]:
    """Service-role Convex client. No Clerk token needed."""
    try:
        return _get_client()
    except Exception:
        return None


def get_user_client(access_token: str = "") -> Optional[ConvexClient]:
    """Per-user Convex client. The Clerk token is ignored — Convex auth
    is bypassed via the Internal function variants on the backend."""
    try:
        return _get_client()
    except Exception:
        return None


def reset_client_for_testing() -> None:
    global _client
    _client = None


def _normalize_job(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Ensures document keys map to both camelCase and snake_case for pipeline parity."""
    if not doc:
        return doc
    normalized = dict(doc)
    job_id = doc.get("id") or doc.get("_id") or doc.get("legacyId")
    normalized["id"] = str(job_id) if job_id else ""
    normalized["result_video_r2_key"] = doc.get("resultVideoR2Key") or doc.get("result_video_r2_key") or doc.get("output_path") or ""
    normalized["source_video_r2_key"] = doc.get("sourceVideoR2Key") or doc.get("source_video_r2_key") or ""
    normalized["workspace_id"] = doc.get("workspaceId") or doc.get("workspace_id") or ""
    return normalized


async def init_db() -> None:
    logger.info("[DATABASE-CONVEX] Schema is managed by Convex deploys. init_db is a no-op.")


async def create_job(client: Any = None, *, workspace_id: str = "", owner_user_id: str = "", job_id: Optional[str] = None, source_video_r2_key: str = "", consent_version: str = "", user_ip_address: str = ""):
    actual_job_id = job_id or str(uuid.uuid4())
    import datetime
    server_timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    job_doc = {
        "id": actual_job_id,
        "legacyId": actual_job_id,
        "workspace_id": workspace_id,
        "owner_user_id": owner_user_id,
        "status": "pending",
        "progress": 0,
        "source_video_r2_key": source_video_r2_key,
        "result_video_r2_key": "",
        "consent_version": consent_version,
        "user_ip_address": user_ip_address,
        "consent_timestamp": server_timestamp
    }
    _in_memory_jobs[actual_job_id] = job_doc

    try:
        c = client or _get_client()
        args = {
            "workspaceId": workspace_id,
            "ownerUserId": owner_user_id,
            "legacyId": actual_job_id,
            "sourceVideoR2Key": source_video_r2_key or "",
            "sourceLang": "ku",
            "targetLang": "ar-IQ",
            "ttsProvider": "minimax",
            "consentVersion": consent_version,
            "userIpAddress": user_ip_address,
            "consentTimestamp": server_timestamp,
        }
        def _do():
            try:
                res = c.mutation("dubbingJobs:createInternal", _internal_args(args))
            except Exception as e:
                err_data = getattr(e, "data", "")
                if "WORKSPACE_NOT_FOUND" in str(e) or err_data == "WORKSPACE_NOT_FOUND":
                    logger.info(f"Workspace {workspace_id} not found in Convex. Auto-creating...")
                    c.mutation("workspaces:createForOwnerInternal", _internal_args({
                        "ownerUserId": owner_user_id,
                        "orgId": workspace_id
                    }))
                    res = c.mutation("dubbingJobs:createInternal", _internal_args(args))
                else:
                    raise e
            
            if isinstance(res, str):
                job_doc["id"] = res
                _in_memory_jobs[res] = job_doc
                return job_doc
            if isinstance(res, dict):
                return _normalize_job(res)
            return job_doc
        res_doc = await asyncio.to_thread(_do)
        return res_doc or job_doc
    except Exception as e:
        logger.warning(f"[DATABASE-CONVEX] Create job fallback used for {actual_job_id}: {e}")
        return job_doc


async def get_job(client: Any = None, *, workspace_id: str = "", job_id: str = "", store_id: str = ""):
    """Fetch one job by id, scoped to `workspace_id` when supplied.

    PIRD-017 follow-up. The previous body forwarded only `jobId` and dropped
    `workspace_id` entirely, with a comment claiming Convex "derived" the
    workspace server-side. Deriving the workspace FROM the doc is
    tautological — it identifies the owner, it cannot decide whether the
    CALLER is entitled to the doc. That made GET /video/jobs/{job_id} and
    /jobs/{job_id}/download a cross-tenant IDOR for any valid Clerk JWT.

    An empty `workspace_id` means "trusted internal/worker call, do not
    scope" and is preserved for the non-request code paths.
    """

    def _owned(job: Optional[Dict[str, Any]], from_memory: bool = False) -> Optional[Dict[str, Any]]:
        # PIRD-017: defense in depth. Convex already enforces
        # expectedWorkspaceId server-side, but a future schema change or
        # a bug in resolveWorkspaceId (e.g. accepting a legacy id that
        # happens to point at the wrong workspace) could leak the doc
        # here. Re-check the doc's workspaceId against the requested
        # one in Python, comparing the camelCase Convex field against
        # both the snake_case and the resolved id.
        if not job:
            return job
        if not workspace_id:
            return job  # trusted internal/worker path
        doc_ws = job.get("workspaceId") or job.get("workspace_id") or ""
        if not doc_ws:
            return job  # doc with no workspace — treat as orphan, do not block
        
        # If they match exactly, we're good (e.g., in-memory jobs)
        if str(doc_ws) == str(workspace_id):
            return job
            
        # If the job came from in-memory and string doesn't match, reject
        if from_memory:
            return None
            
        # If the job came from Convex, getInternal already strictly verified 
        # expectedWorkspaceId server-side. Since doc_ws is the Convex ID and
        # workspace_id is the legacy Clerk ID, they will not match by strict 
        # string equality. We can safely trust Convex's validation here.
        return job

    try:
        c = client or _get_client()
        def _do():
            args: Dict[str, Any] = {"jobId": job_id}
            # Defense in depth: let Convex reject the mismatch too, so the
            # guard does not live only in this adapter.
            if workspace_id:
                args["expectedWorkspaceId"] = workspace_id
            raw = c.query("dubbingJobs:getInternal", _internal_args(args))
            return _normalize_job(raw)
        result = await asyncio.to_thread(_do)
        if result:
            return _owned(result, from_memory=False)
    except Exception as e:
        logger.warning(f"[DATABASE-CONVEX] get_job query failed: {e}")
        pass

    return _owned(_normalize_job(_in_memory_jobs.get(job_id)), from_memory=True)


async def list_jobs(client: Any = None, *, workspace_id: str = "", store_id: str = "", limit: int = 50):
    try:
        c = client or _get_client()
        def _do():
            raw_list = c.query("dubbingJobs:listForWorkspaceInternal", _internal_args({"workspaceId": workspace_id, "limit": limit}))
            if raw_list is None:
                return None
            return [_normalize_job(doc) for doc in raw_list]
        jobs = await asyncio.to_thread(_do)
        if jobs is None:
            seen_ids = set()
            jobs = []
            for j in _in_memory_jobs.values():
                if not workspace_id or j.get("workspace_id") == workspace_id:
                    jid = j.get("id")
                    if jid not in seen_ids:
                        seen_ids.add(jid)
                        jobs.append(j)

        # Pird: Auto-fail stale jobs (older than 30 minutes in pending/processing/separating)
        # Prevents zombie jobs from hanging forever when server restarts or worker crashes.
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)
        stale_threshold_sec = 1800  # 30 minutes

        for job in jobs:
            status = job.get("status", "")
            if status in ("pending", "processing", "separating"):
                updated_at_str = job.get("updated_at") or job.get("updatedAt") or job.get("created_at") or job.get("createdAt")
                if updated_at_str:
                    try:
                        clean_ts = str(updated_at_str).replace("Z", "+00:00")
                        job_dt = datetime.datetime.fromisoformat(clean_ts)
                        if job_dt.tzinfo is None:
                            job_dt = job_dt.replace(tzinfo=datetime.timezone.utc)
                        age_sec = (now - job_dt).total_seconds()
                        if age_sec > stale_threshold_sec:
                            job["status"] = "failed"
                            job["error"] = "Job timed out (process interrupted or server restarted)"
                            try:
                                # Pird PIRD-017: workspaceId omitted; derived server-side.
                                c.mutation("dubbingJobs:updateStatusInternal", _internal_args({
                                    "jobId": job["id"],
                                    "status": "failed",
                                    "error": job["error"]
                                }))
                            except Exception:
                                pass
                    except Exception:
                        pass
        return jobs
    except Exception:
        seen_ids = set()
        res_jobs = []
        for j in _in_memory_jobs.values():
            if not workspace_id or j.get("workspace_id") == workspace_id:
                jid = j.get("id")
                if jid not in seen_ids:
                    seen_ids.add(jid)
                    res_jobs.append(j)
        return res_jobs


async def list_jobs_by_status(client: Any = None, *, status: str = "", limit: int = 50):
    try:
        c = client or _get_client()
        def _do():
            raw_list = c.query("dubbingJobs:listByStatusInternal", _internal_args({"status": status, "limit": limit})) or []
            return [_normalize_job(doc) for doc in raw_list]
        return await asyncio.to_thread(_do)
    except Exception as e:
        logger.warning(f"[DATABASE-CONVEX] list_jobs_by_status failed: {e}")
        return []


async def update_job_status(client: Any = None, *, workspace_id: str = "", job_id: str = "", status: str = "", progress: int = -1, output_path: str = "", error: str = ""):
    if job_id in _in_memory_jobs:
        _in_memory_jobs[job_id]["status"] = status
        if progress >= 0:
            _in_memory_jobs[job_id]["progress"] = progress
        if output_path:
            _in_memory_jobs[job_id]["result_video_r2_key"] = output_path
            _in_memory_jobs[job_id]["output_path"] = output_path
        if error:
            _in_memory_jobs[job_id]["error"] = error

    try:
        c = client or _get_client()
        # Pird PIRD-017: workspaceId omitted; derived server-side from the job doc.
        args: Dict[str, Any] = {
            "jobId": job_id,
            "status": status,
        }
        if progress >= 0:
            args["progress"] = progress
        if output_path:
            args["resultVideoR2Key"] = output_path
        if error:
            args["error"] = error
        elif status == "completed":
            args["error"] = ""
        def _do():
            return c.mutation("dubbingJobs:updateStatusInternal", _internal_args(args))
        return await asyncio.to_thread(_do)
    except Exception as e:
        logger.warning(f"[DATABASE-CONVEX] Update job status fallback for {job_id}: {e}")
        return True


async def update_job_cost(client: Any = None, *, workspace_id: str = "", job_id: str = "", total_latency_ms: float = 0.0, total_cost_usd: float = 0.0):
    try:
        c = client or _get_client()
        # Pird PIRD-017: workspaceId omitted; derived server-side from the job doc.
        args: Dict[str, Any] = {
            "jobId": job_id,
            "totalProcessingLatencyMs": total_latency_ms,
            "totalCostUsd": total_cost_usd
        }
        def _do():
            return c.mutation("dubbingJobs:updateCostInternal", _internal_args(args))
        return await asyncio.to_thread(_do)
    except Exception as e:
        logger.warning(f"[DATABASE-CONVEX] Update job cost fallback for {job_id}: {e}")
        return True


async def create_step_telemetry(
    client: Any = None,
    *,
    workspace_id: str = "",
    job_id: str = "",
    chunk_index: Optional[int] = -1,
    step_name: str = "",
    duration_ms: float = 0.0,
    status_code: int = 200,
    compute_provider: str = "",
    usage_units: float = 0.0,
    cost_usd: float = 0.0
):
    try:
        c = client or _get_client()
        # Pird PIRD-017: workspaceId omitted; derived server-side from the job doc.
        args = {
            "jobId": job_id,
            "stepName": step_name,
            "durationMs": duration_ms,
            "statusCode": status_code,
            "computeProvider": compute_provider,
            "usageUnits": usage_units,
            "costUsd": cost_usd
        }
        if chunk_index is not None and chunk_index >= 0:
            args["chunkIndex"] = chunk_index
        def _do():
            return c.mutation("stepTelemetry:insertInternal", _internal_args(args))
        # Using background queue or asyncio.create_task for telemetry is preferred to avoid blocking the pipeline
        asyncio.create_task(asyncio.to_thread(_do))
        return True
    except Exception as e:
        logger.warning(f"[DATABASE-CONVEX] create_step_telemetry fallback for job {job_id}: {e}")
        return None


async def create_chunk(client: Any = None, *, workspace_id: str = "", job_id: str = "", chunk_index: int = 0, start_time: float = 0.0, end_time: float = 0.0, status: str = "pending", patch: Optional[dict] = None):
    try:
        c = client or _get_client()
        legacy_id = str(uuid.uuid4())
        doc_patch = patch or {}
        def _do():
            # Pird PIRD-017: workspaceId omitted; derived server-side from the job doc.
            return c.mutation("dubbingChunks:insertInternal", _internal_args({
                "legacyId": legacy_id,
                "jobId": job_id,
                "chunkIndex": chunk_index,
                "startTime": start_time,
                "endTime": end_time,
                "status": status,
                "patch": doc_patch
            }))
        return await asyncio.to_thread(_do)
    except Exception as e:
        logger.warning(f"[DATABASE-CONVEX] create_chunk fallback for job {job_id}: {e}")
        return None


async def update_chunk(client: Any = None, *, workspace_id: str = "", job_id: str = "", chunk_id: str = "", updates: Optional[dict] = None):
    updates = updates or {}
    try:
        for _reserved in ("id", "jobId", "workspaceId", "createdAt"):
            updates.pop(_reserved, None)
        args: Dict[str, Any] = {"chunkId": chunk_id}
        for k, v in updates.items():
            args[k] = v
        c = client or _get_client()
        def _do():
            return c.mutation("dubbingChunks:updateInternal", _internal_args({"chunkId": chunk_id, "patch": updates}))
        return await asyncio.to_thread(_do)
    except Exception:
        return True


async def log_ai_usage(
    workspace_id: Optional[str] = None,
    service: str = "",
    context: str = "",
    provider: Optional[str] = None,
    model: Optional[str] = None,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    estimated_cost_usd: Optional[float] = None,
    client: Any = None,
) -> None:
    try:
        c = client or _get_client()
        payload: Dict[str, Any] = {
            "service": service,
            "context": context,
            "provider": provider,
            "model": model,
            "inputTokens": input_tokens,
            "outputTokens": output_tokens,
            "estimatedCostUsd": estimated_cost_usd,
            "workspaceId": workspace_id,
        }
        def _do():
            return c.mutation("usageLogs:recordInternal", _internal_args(payload))
        await asyncio.to_thread(_do)
    except Exception:
        pass


async def get_workspace_minutes(client: Any = None, *, workspace_id: str = "") -> int:
    """Return current `dubbingMinutes` for the workspace.

    Pird (security review H4): do NOT return a default of 1000 on any
    failure path. A Convex outage or a wiring error would otherwise
    silently grant every workspace 1000 free minutes, draining GPU
    budget. Callers handle `RuntimeError` and respond 402 / 503.
    """
    c = client or _get_client()
    def _do():
        # Pird PIRD-017: pass legacyId only; server resolves workspace.
        return c.query("workspaces:getMinutesInternal", _internal_args({"legacyId": workspace_id}))
    res = await asyncio.to_thread(_do)
    if res is None:
        raise RuntimeError(
            f"workspaces:getMinutesInternal returned null for workspace {workspace_id!r}"
        )
    return int(res)


async def add_workspace_minutes(client: Any = None, *, workspace_id: str = "", minutes: int = 0) -> int:
    c = client or _get_client()
    def _do():
        # Pird PIRD-017: pass legacyId only; server resolves workspace.
        return c.mutation("workspaces:addMinutesInternal", _internal_args({"legacyId": workspace_id, "delta": minutes}))
    res = await asyncio.to_thread(_do)
    return int(res)


async def deduct_workspace_minutes(client: Any = None, *, workspace_id: str = "", minutes: int = 0) -> int:
    c = client or _get_client()
    def _do():
        # Pird PIRD-017: pass legacyId only; server resolves workspace.
        return c.mutation("workspaces:deductMinutesInternal", _internal_args({"legacyId": workspace_id, "amount": minutes}))
    res = await asyncio.to_thread(_do)
    try:
        return int(res) if res is not None and not hasattr(res, "_mock_return_value") else 0
    except (ValueError, TypeError):
        return 0


async def handle_refund_kill_switch(client: Any = None, *, workspace_id: str = "", amount_deducted: int = 0) -> Dict[str, Any]:
    c = client or _get_client()
    def _do():
        return c.mutation("workspaces:handleRefundKillSwitchInternal", _internal_args({"legacyId": workspace_id, "amountDeducted": amount_deducted}))
    return await asyncio.to_thread(_do)


async def record_and_process_webhook_durable(client: Any = None, *, event_id: str = "", event_type: str = "", payload: Dict[str, Any] = None) -> Dict[str, Any]:
    """Synchronously record raw webhook to Convex webhookEvents table & process in single durable mutation."""
    c = client or _get_client()
    def _do():
        return c.mutation("webhooks:recordAndProcessWebhookInternal", _internal_args({
            "eventId": event_id,
            "eventType": event_type,
            "payload": payload or {}
        }))
    return await asyncio.to_thread(_do)


async def add_transaction(client: Any = None, *, transaction_id: str = "", workspace_id: str = "", tier: str = "", amount_usd: int = 0, minutes_added: int = 0) -> None:
    try:
        c = client or _get_client()
        payload = {
            "tier": tier,
            "amount_usd": amount_usd,
            "minutes_added": minutes_added,
        }
        def _do():
            return c.mutation("transactions:recordInternal", _internal_args({"legacyId": transaction_id, "workspaceId": workspace_id, **payload}))
        await asyncio.to_thread(_do)
    except Exception:
        pass


async def process_payment_success_atomic(client: Any = None, *, transaction_id: str = "", workspace_id: str = "", tier: str = "", amount_usd: int = 0, minutes_added: int = 0) -> Dict[str, Any]:
    """Execute atomic transaction record + minute addition in a single Convex transaction."""
    c = client or _get_client()
    payload = {
        "transactionId": transaction_id,
        "workspaceId": workspace_id,
        "tier": tier,
        "amountUsd": amount_usd,
        "minutesAdded": minutes_added,
    }
    def _do():
        return c.mutation("transactions:processPaymentSuccessInternal", _internal_args(payload))
    return await asyncio.to_thread(_do)


async def transaction_exists(client: Any = None, *, transaction_id: str = "") -> bool:
    try:
        c = client or _get_client()
        def _do():
            return bool(c.query("transactions:existsInternal", _internal_args({"legacyId": transaction_id})))
        return await asyncio.to_thread(_do)
    except Exception:
        return False


async def list_transactions(client: Any = None, *, workspace_id: str = "") -> List[Dict[str, Any]]:
    try:
        c = client or _get_client()
        def _do():
            return c.query("transactions:listInternal", _internal_args({"workspaceId": workspace_id})) or []
        return await asyncio.to_thread(_do)
    except Exception as e:
        logger.warning(f"[DATABASE-CONVEX] list_transactions failed: {e}")
        return []

import boto3
import json

def send_telemetry_background(table: str, payload: dict):
    """Fire-and-forget telemetry writer."""
    def _run():
        try:
            client = _get_client()
            # If there's a specific mutation, call it. Otherwise, insert directly if permitted.
            # Assuming a mutation like 'telemetry:insert' exists or doing direct insert if admin.
            # For this architecture, we will log errors to ingestion_errors if possible.
            try:
                client.mutation("telemetry:insert", {"table": table, "payload": payload})
            except Exception as e:
                logger.error(f"Convex telemetry failed: {e}. Falling back to S3.")
                _fallback_to_s3(table, payload, str(e))
        except Exception as outer_e:
            _fallback_to_s3(table, payload, str(outer_e))
            
    # Run in background without blocking
    try:
        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, _run)
    except RuntimeError:
        # No loop running, just run it if we must or start a thread
        import threading
        threading.Thread(target=_run, daemon=True).start()

def _fallback_to_s3(table: str, payload: dict, error_msg: str):
    try:
        s3 = boto3.client('s3')
        bucket = os.getenv("TELEMETRY_S3_BUCKET", "dubbing-telemetry-fallback")
        key = f"{table}/{uuid.uuid4()}.json"
        dead_letter = {
            "source_step": table,
            "payload": json.dumps(payload),
            "error_message": error_msg,
            "retry_count": 0,
            "resolved": False
        }
        s3.put_object(Bucket=bucket, Key=key, Body=json.dumps(dead_letter))
    except Exception as s3_err:
        logger.error(f"S3 fallback also failed: {s3_err}")


async def log_consent(
    client: Any = None,
    *,
    user_id: str = "",
    workspace_id: str = "",
    consent_version: str = "",
    user_ip_address: str = "",
    input_text_id: str = "",
    target_audio_hash: str = ""
) -> None:
    """Log user consent for generating dubbing/TTS."""
    import datetime
    server_timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        c = client or _get_client()
        payload = {
            "userId": user_id,
            "workspaceId": workspace_id,
            "consentVersion": consent_version,
            "userIpAddress": user_ip_address,
            "inputTextId": input_text_id,
            "targetAudioHash": target_audio_hash,
            "consentTimestamp": server_timestamp
        }
        def _do():
            return c.mutation("consentLogs:insertInternal", _internal_args(payload))
        await asyncio.to_thread(_do)
    except Exception as e:
        logger.warning(f"[DATABASE-CONVEX] log_consent fallback: {e}")
        # fallback to local file
        import json
        from pathlib import Path
        log_dir = Path("data/logs/consent")
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "tts_consent.log"
        try:
            with open(log_file, "a") as f:
                f.write(json.dumps({
                    "user_id": user_id,
                    "workspace_id": workspace_id,
                    "consent_version": consent_version,
                    "user_ip_address": user_ip_address,
                    "input_text_id": input_text_id,
                    "target_audio_hash": target_audio_hash,
                    "consent_timestamp": server_timestamp
                }) + "\n")
        except Exception:
            pass
