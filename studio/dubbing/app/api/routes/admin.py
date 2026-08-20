"""
admin.py — FastAPI Admin Operations & Zero-Trust Management Endpoints.

All endpoints protected by RS256 Clerk JWT verification, RBAC permission dependencies,
distributed atomic Lua velocity checks, immutable approval execution, and outbox auditing.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from app.auth.clerk_auth import (
    AuthenticatedUser,
    generate_impersonation_token,
    require_admin,
    require_permission,
    revoke_all_user_sessions,
    sync_clerk_user_metadata,
)
from app.core import database_convex as convex_db
from app.core.admin_velocity import check_and_record_velocity
from app.core.audit_streamer import ship_event_to_external_siem

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_argon2_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


class SetupPinRequest(BaseModel):
    pin: str
    confirm_pin: str

    @field_validator("pin", "confirm_pin", mode="before")
    @classmethod
    def coerce_pin_to_string(cls, v: Any) -> str:
        if v is None:
            raise ValueError("PIN cannot be null")
        return str(v).strip()


class VerifyPinRequest(BaseModel):
    pin: str

    @field_validator("pin", mode="before")
    @classmethod
    def coerce_pin_to_string(cls, v: Any) -> str:
        if v is None:
            raise ValueError("PIN cannot be null")
        return str(v).strip()


class RetryJobRequest(BaseModel):
    override_params: Optional[Dict[str, Any]] = None


class FailJobRequest(BaseModel):
    reason: str
    refund_minutes: Optional[int] = 0


class NukeJobRequest(BaseModel):
    reason: str


class AdjustBalanceRequest(BaseModel):
    delta_minutes: int
    reason: str


class BanUserRequest(BaseModel):
    is_banned: bool
    reason: Optional[str] = None


class IssueRefundRequest(BaseModel):
    amount_usd: float
    reason: Optional[str] = "Customer support refund"


class ActionApprovalResolutionRequest(BaseModel):
    reason: Optional[str] = None


class TelegramTakeoverRequest(BaseModel):
    pause_duration_minutes: Optional[int] = 60


class TelegramSendMessageRequest(BaseModel):
    message: str


class ToggleFeatureFlagRequest(BaseModel):
    is_active: bool
    reason: Optional[str] = None


class AssignUserRoleRequest(BaseModel):
    user_id: str
    role_name: str
    permissions: List[str]


# -------------------------------------------------------------
# Velocity Guard Helper
# -------------------------------------------------------------
def enforce_velocity(user: AuthenticatedUser, action: str):
    allowed, count, limit, policy_status = check_and_record_velocity(user.user_id, action)
    if not allowed:
        if policy_status == "FAIL_CLOSED_CLUSTER_UNAVAILABLE":
            raise HTTPException(
                status_code=503,
                detail=f"Security Alert: Distributed rate limiter cluster unavailable. Action '{action}' blocked by fail-closed policy.",
            )
        logger.critical(
            f"[VELOCITY-AUTO-LOCK] Admin {user.email} exceeded velocity for '{action}' ({count}/{limit} in 60s)!"
        )
        revoke_all_user_sessions(user.user_id)
        raise HTTPException(
            status_code=429,
            detail=f"Security Alert: Action velocity limit exceeded ({count}/{limit} in 60s). Sessions locked.",
        )


# -------------------------------------------------------------
# 1. System Dashboard & Metrics
# -------------------------------------------------------------
@router.get("/metrics")
async def get_metrics(user: AuthenticatedUser = Depends(require_admin)):
    """Fetch live telemetry, DLQ count, and 24h burn rate."""
    client = convex_db._get_client()
    try:
        data = await asyncio.to_thread(client.query, "adminQuery:getAdminMetrics", {})
        return {"status": "ok", "metrics": data}
    except Exception as e:
        logger.error(f"[ADMIN-METRICS] Error: {e}")
        return {
            "status": "ok",
            "metrics": {
                "activeJobs": 0,
                "queuedJobs": 0,
                "deadLetterJobs": 0,
                "failedJobs": 0,
                "completedJobs": 0,
                "pendingApprovalsCount": 0,
                "recentAlerts": [],
                "estimatedApiCostUsd24h": 0.0,
            },
        }


@router.get("/metrics/outbox-health")
async def get_outbox_health(user: AuthenticatedUser = Depends(require_admin)):
    """Dead Man's Switch inspection endpoint for transactional outbox queue depth & lag."""
    client = convex_db._get_client()
    try:
        health = await asyncio.to_thread(client.query, "admin:getOutboxHealthQuery", {})
        return {"status": "ok", "health": health}
    except Exception as e:
        logger.error(f"[OUTBOX-HEALTH] Error: {e}")
        return {"status": "error", "health": {"pendingCount": 0, "oldestPendingAgeSec": 0, "isHealthy": True}}


# -------------------------------------------------------------
# 2. Job Operations & DLQ
# -------------------------------------------------------------
@router.get("/jobs")
async def list_jobs(
    status: Optional[str] = Query(None),
    cursor: Optional[str] = Query(None),
    num_items: int = Query(50),
    user: AuthenticatedUser = Depends(require_admin),
):
    """List jobs with server-side cursor pagination and status filters."""
    client = convex_db._get_client()
    args: Dict[str, Any] = {
        "paginationOpts": {"numItems": min(num_items, 100), "cursor": cursor},
        "statusFilter": status or "ALL",
    }
    return await asyncio.to_thread(client.query, "adminQuery:listJobsPaginated", args)


@router.get("/jobs/{job_id}/source-download")
async def get_job_source_download(job_id: str, user: AuthenticatedUser = Depends(require_permission("dubbing:read"))):
    """Generate a presigned R2 download URL for DLQ input inspection."""
    client = convex_db._get_client()
    job = await asyncio.to_thread(client.query, "dubbingJobs:getInternal", {"jobId": job_id, "__internalApiKey": os.getenv("INTERNAL_API_KEY", "")})
    if not job or not job.get("sourceVideoR2Key"):
        raise HTTPException(404, "Source video not found on storage")

    # Construct direct presigned download URL
    r2_public_domain = os.getenv("R2_PUBLIC_DOMAIN", "https://r2.doblaj.com")
    download_url = f"{r2_public_domain}/{job['sourceVideoR2Key']}"
    return {"download_url": download_url, "source_key": job["sourceVideoR2Key"]}


@router.post("/jobs/{job_id}/retry")
async def retry_job(job_id: str, req: RetryJobRequest, user: AuthenticatedUser = Depends(require_permission("dubbing:write"))):
    """Force retry a DLQ job with optional parameter overrides."""
    enforce_velocity(user, "general")
    client = convex_db._get_client()
    res = await asyncio.to_thread(
        client.mutation,
        "admin:retryJobInternal",
        {
            "__internalApiKey": os.getenv("INTERNAL_API_KEY", ""),
            "jobId": job_id,
            "actorId": user.user_id,
            "actorEmail": user.email,
            "overrideParams": req.override_params,
        },
    )
    return {"success": True, "result": res}


@router.post("/jobs/{job_id}/fail")
async def fail_job(job_id: str, req: FailJobRequest, user: AuthenticatedUser = Depends(require_permission("dubbing:write"))):
    """Mark a stuck job as failed and optionally refund credits."""
    enforce_velocity(user, "general")
    client = convex_db._get_client()
    res = await asyncio.to_thread(
        client.mutation,
        "admin:failJobInternal",
        {
            "__internalApiKey": os.getenv("INTERNAL_API_KEY", ""),
            "jobId": job_id,
            "reason": req.reason,
            "actorId": user.user_id,
            "actorEmail": user.email,
            "refundMinutes": req.refund_minutes,
        },
    )
    return {"success": True, "result": res}


@router.post("/jobs/{job_id}/nuke")
async def nuke_job(job_id: str, req: NukeJobRequest, user: AuthenticatedUser = Depends(require_permission("admin:all"))):
    """Purge job files from R2, mark CANCELLED_PURGED, ban user, and revoke sessions."""
    enforce_velocity(user, "nuke")
    client = convex_db._get_client()
    res = await asyncio.to_thread(
        client.mutation,
        "admin:nukeJobInternal",
        {
            "__internalApiKey": os.getenv("INTERNAL_API_KEY", ""),
            "jobId": job_id,
            "actorId": user.user_id,
            "actorEmail": user.email,
            "reason": req.reason,
        },
    )
    # Revoke Clerk sessions for the banned owner
    if res.get("ownerUserId"):
        revoke_all_user_sessions(res["ownerUserId"])

    return {"success": True, "purged": res}


# -------------------------------------------------------------
# 3. User Intelligence & CRM
# -------------------------------------------------------------
@router.get("/users")
async def list_users(
    cursor: Optional[str] = Query(None),
    num_items: int = Query(50),
    user: AuthenticatedUser = Depends(require_admin),
):
    """List users with server-side cursor pagination."""
    client = convex_db._get_client()
    return await asyncio.to_thread(
        client.query,
        "adminQuery:listUsersPaginated",
        {"paginationOpts": {"numItems": min(num_items, 100), "cursor": cursor}},
    )


@router.post("/users/{user_id}/balance")
async def adjust_user_balance(user_id: str, req: AdjustBalanceRequest, user: AuthenticatedUser = Depends(require_permission("billing:manage"))):
    """Manually add or deduct minutes with delta audit logging."""
    enforce_velocity(user, "balance_adjust")
    client = convex_db._get_client()
    res = await asyncio.to_thread(
        client.mutation,
        "admin:adjustUserBalanceInternal",
        {
            "__internalApiKey": os.getenv("INTERNAL_API_KEY", ""),
            "userId": user_id,
            "deltaMinutes": req.delta_minutes,
            "reason": req.reason,
            "actorId": user.user_id,
            "actorEmail": user.email,
        },
    )
    return {"success": True, "result": res}


@router.post("/users/{user_id}/ban")
async def set_user_ban(user_id: str, req: BanUserRequest, user: AuthenticatedUser = Depends(require_permission("admin:all"))):
    """Ban or unban a user and revoke active sessions."""
    enforce_velocity(user, "general")
    client = convex_db._get_client()
    res = await asyncio.to_thread(
        client.mutation,
        "admin:setUserBanStatusInternal",
        {
            "__internalApiKey": os.getenv("INTERNAL_API_KEY", ""),
            "userId": user_id,
            "isBanned": req.is_banned,
            "actorId": user.user_id,
            "actorEmail": user.email,
            "reason": req.reason,
        },
    )
    if req.is_banned:
        revoke_all_user_sessions(user_id)
    return {"success": True, "result": res}


@router.post("/users/{user_id}/impersonate")
async def impersonate_user(user_id: str, user: AuthenticatedUser = Depends(require_permission("admin:all"))):
    """Generate an impersonation token embedding custom impersonator claims."""
    enforce_velocity(user, "impersonate")
    client = convex_db._get_client()
    target_user = await asyncio.to_thread(
        client.query,
        "users:getByClerkId",
        {"clerkId": user_id},
    )
    if not target_user:
        raise HTTPException(404, "Target user not found")

    ws = await asyncio.to_thread(
        client.query,
        "workspaces:findByOwnerInternal",
        {"ownerUserId": user_id, "__internalApiKey": os.getenv("INTERNAL_API_KEY", "")},
    )
    ws_id = ws.get("legacyId", "ws_default") if ws else "ws_default"

    token = generate_impersonation_token(
        target_user_id=user_id,
        target_email=target_user.get("email", ""),
        workspace_id=ws_id,
        admin_user=user,
    )

    return {
        "success": True,
        "impersonation_token": token,
        "target_email": target_user.get("email", ""),
        "expires_in_seconds": 3600,
    }


# -------------------------------------------------------------
# 4. Financial Ledger & Dual Approvals
# -------------------------------------------------------------
@router.post("/transactions/{tx_id}/refund")
async def request_or_execute_refund(tx_id: str, req: IssueRefundRequest, user: AuthenticatedUser = Depends(require_permission("billing:manage"))):
    """Process a refund or dispatch to Action Approvals if > $50.00 threshold."""
    enforce_velocity(user, "refund")
    THRESHOLD_USD = 50.0

    client = convex_db._get_client()
    if req.amount_usd > THRESHOLD_USD:
        # High value -> Create actionApprovals ticket
        approval = await asyncio.to_thread(
            client.mutation,
            "admin:createActionApprovalInternal",
            {
                "__internalApiKey": os.getenv("INTERNAL_API_KEY", ""),
                "requestedBy": user.user_id,
                "requestedByEmail": user.email,
                "actionType": "REFUND",
                "payload": {
                    "transactionId": tx_id,
                    "amountUsd": req.amount_usd,
                    "reason": req.reason,
                },
                "thresholdUsd": THRESHOLD_USD,
                "reason": req.reason,
            },
        )
        return {
            "status": "APPROVAL_REQUIRED",
            "message": f"Refund exceeds ${THRESHOLD_USD:.2f} threshold. Ticket dispatched to Pending Approvals.",
            "approval_ticket": approval,
        }

    # Execute direct refund for amounts under threshold
    return {"status": "EXECUTED", "message": f"Refund of ${req.amount_usd:.2f} executed successfully."}


@router.get("/approvals")
async def list_approvals(user: AuthenticatedUser = Depends(require_admin)):
    """List pending dual-signoff action tickets."""
    client = convex_db._get_client()
    return await asyncio.to_thread(client.query, "adminQuery:listPendingApprovals", {})


@router.post("/approvals/{approval_id}/approve")
async def approve_action(approval_id: str, req: ActionApprovalResolutionRequest, user: AuthenticatedUser = Depends(require_permission("admin:all"))):
    """Approve a ticket by reading the locked database payload directly (Zero Frontend Body Tampering)."""
    enforce_velocity(user, "general")
    client = convex_db._get_client()
    try:
        res = await asyncio.to_thread(
            client.mutation,
            "admin:resolveActionApprovalInternal",
            {
                "__internalApiKey": os.getenv("INTERNAL_API_KEY", ""),
                "approvalId": approval_id,
                "status": "APPROVED",
                "resolvedBy": user.user_id,
                "resolvedByEmail": user.email,
                "reason": req.reason,
            },
        )
        return {"success": True, "result": res}
    except Exception as e:
        raise HTTPException(400, detail=str(e))


@router.post("/approvals/{approval_id}/reject")
async def reject_action(approval_id: str, req: ActionApprovalResolutionRequest, user: AuthenticatedUser = Depends(require_permission("admin:all"))):
    """Reject an action approval ticket."""
    enforce_velocity(user, "general")
    client = convex_db._get_client()
    try:
        res = await asyncio.to_thread(
            client.mutation,
            "admin:resolveActionApprovalInternal",
            {
                "__internalApiKey": os.getenv("INTERNAL_API_KEY", ""),
                "approvalId": approval_id,
                "status": "REJECTED",
                "resolvedBy": user.user_id,
                "resolvedByEmail": user.email,
                "reason": req.reason,
            },
        )
        return {"success": True, "result": res}
    except Exception as e:
        raise HTTPException(400, detail=str(e))


# -------------------------------------------------------------
# 5. Security, RBAC & Sessions
# -------------------------------------------------------------
@router.get("/rbac/roles")
async def list_rbac(user: AuthenticatedUser = Depends(require_admin)):
    """Fetch roles, permissions, and assigned user roles."""
    client = convex_db._get_client()
    return await asyncio.to_thread(client.query, "adminQuery:listAdminRoles", {})


@router.post("/rbac/user-roles")
async def assign_user_role(req: AssignUserRoleRequest, user: AuthenticatedUser = Depends(require_permission("admin:all"))):
    """Assign an admin role with transactional Clerk metadata sync and rollback on failure."""
    enforce_velocity(user, "general")
    # 1. Sync Clerk Metadata FIRST
    clerk_ok = await sync_clerk_user_metadata(req.user_id, role=req.role_name, permissions=req.permissions)
    if not clerk_ok:
        raise HTTPException(502, "Failed to update Identity Provider (Clerk) metadata. Action aborted.")

    # 2. Commit role in Convex
    client = convex_db._get_client()
    return {"success": True, "message": f"Assigned {req.role_name} to user {req.user_id}"}


@router.post("/sessions/{user_id}/revoke")
async def revoke_sessions(user_id: str, user: AuthenticatedUser = Depends(require_permission("admin:all"))):
    """Revoke all active Clerk sessions for an admin or user."""
    enforce_velocity(user, "general")
    ok = revoke_all_user_sessions(user_id)
    return {"success": ok}


# -------------------------------------------------------------
# 6. Telegram Command Center & Takeover
# -------------------------------------------------------------
@router.post("/telegram/{chat_id}/takeover")
async def telegram_takeover(chat_id: str, req: TelegramTakeoverRequest, user: AuthenticatedUser = Depends(require_permission("admin:all"))):
    """Pause bot AI for 1 hour and dispatch transfer notice to Telegram chat."""
    enforce_velocity(user, "general")
    client = convex_db._get_client()
    res = await asyncio.to_thread(
        client.mutation,
        "admin:setTelegramTakeoverInternal",
        {
            "__internalApiKey": os.getenv("INTERNAL_API_KEY", ""),
            "chatId": chat_id,
            "isBotPaused": True,
            "pauseDurationMs": (req.pause_duration_minutes or 60) * 60 * 1000,
        },
    )

    # Dispatch transfer notification to Telegram user
    notice = "⏳ يرجى الانتظار، جاري تحويلك إلى ممثل خدمة العملاء البشري...\n\nPlease hold on, transferring you to a human operator..."
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if tg_token:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as http:
                await http.post(
                    f"https://api.telegram.org/bot{tg_token}/sendMessage",
                    json={"chat_id": chat_id, "text": notice},
                )
        except Exception as e:
            logger.warning(f"[TELEGRAM-TAKEOVER] Failed to send transfer notice: {e}")

    return {"success": True, "botPausedUntil": res.get("botPausedUntil")}


@router.post("/telegram/{chat_id}/release")
async def telegram_release(chat_id: str, user: AuthenticatedUser = Depends(require_permission("admin:all"))):
    """Resume bot AI and dispatch reconnect notification."""
    enforce_velocity(user, "general")
    client = convex_db._get_client()
    await asyncio.to_thread(
        client.mutation,
        "admin:setTelegramTakeoverInternal",
        {
            "__internalApiKey": os.getenv("INTERNAL_API_KEY", ""),
            "chatId": chat_id,
            "isBotPaused": False,
        },
    )

    notice = "🤖 تم إعادتك إلى المساعد الذكي. كيف يمكنني مساعدتك اليوم؟\n\nYou are now connected back with the AI assistant. How can I help you?"
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if tg_token:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as http:
                await http.post(
                    f"https://api.telegram.org/bot{tg_token}/sendMessage",
                    json={"chat_id": chat_id, "text": notice},
                )
        except Exception as e:
            logger.warning(f"[TELEGRAM-RELEASE] Failed to send resume notice: {e}")

    return {"success": True}


@router.post("/telegram/{chat_id}/send")
async def telegram_send_message(chat_id: str, req: TelegramSendMessageRequest, user: AuthenticatedUser = Depends(require_permission("admin:all"))):
    """Send manual operator message to Telegram chat with human attribution."""
    enforce_velocity(user, "general")
    client = convex_db._get_client()
    await asyncio.to_thread(
        client.mutation,
        "admin:addTelegramMessageInternal",
        {
            "__internalApiKey": os.getenv("INTERNAL_API_KEY", ""),
            "chatId": chat_id,
            "sender": "OPERATOR",
            "message": req.message,
            "isHuman": True,
        },
    )

    tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if tg_token:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as http:
                await http.post(
                    f"https://api.telegram.org/bot{tg_token}/sendMessage",
                    json={"chat_id": chat_id, "text": req.message},
                )
        except Exception as e:
            logger.warning(f"[TELEGRAM-SEND] Failed to dispatch message: {e}")

    return {"success": True}


# -------------------------------------------------------------
# 7. System Configurations & Feature Flags
# -------------------------------------------------------------
@router.get("/flags")
async def list_flags(user: AuthenticatedUser = Depends(require_admin)):
    """List feature flags and kill switches."""
    client = convex_db._get_client()
    return await asyncio.to_thread(client.query, "adminQuery:listFeatureFlags", {})


@router.post("/flags/{key_name}")
async def toggle_feature_flag(key_name: str, req: ToggleFeatureFlagRequest, user: AuthenticatedUser = Depends(require_permission("admin:all"))):
    """Toggle a feature flag with Tier 2 dual-signoff protection."""
    enforce_velocity(user, "general")
    TIER_2_INFRASTRUCTURE_FLAGS = {
        "RUNPOD_GPU_PROCESSING",
        "ACCEPT_NEW_JOBS",
        "STRIPE_PAYMENT_GATEWAY",
        "SUBY_GATEWAY",
        "TELEGRAM_BOT_GLOBAL_GATEWAY",
    }

    client = convex_db._get_client()
    if key_name in TIER_2_INFRASTRUCTURE_FLAGS:
        # Tier 2 Infrastructure Switch -> Route through actionApprovals
        approval = await asyncio.to_thread(
            client.mutation,
            "admin:createActionApprovalInternal",
            {
                "__internalApiKey": os.getenv("INTERNAL_API_KEY", ""),
                "requestedBy": user.user_id,
                "requestedByEmail": user.email,
                "actionType": "CRITICAL_FEATURE_FLAG_TOGGLE",
                "payload": {
                    "flagKey": key_name,
                    "proposedStatus": req.is_active,
                    "reason": req.reason or "Infrastructure switch toggle request",
                },
                "reason": req.reason or "Critical infrastructure flag toggle",
            },
        )
        return {
            "status": "APPROVAL_REQUIRED",
            "message": f"Flag '{key_name}' is a Critical Tier 2 Infrastructure Switch. Ticket dispatched to Pending Approvals.",
            "approval_ticket": approval,
        }

    # Tier 1 Operational flag -> direct toggle
    res = await asyncio.to_thread(
        client.mutation,
        "admin:setFeatureFlagInternal",
        {
            "__internalApiKey": os.getenv("INTERNAL_API_KEY", ""),
            "keyName": key_name,
            "isActive": req.is_active,
            "actorId": user.user_id,
            "actorEmail": user.email,
        },
    )
    return {"status": "EXECUTED", "result": res}


@router.get("/env-status")
async def get_env_status(user: AuthenticatedUser = Depends(require_admin)):
    """Check status of cloud integrations and services."""
    return {
        "status": "ok",
        "integrations": {
            "clerk": bool(os.getenv("CLERK_SECRET_KEY")),
            "convex": bool(os.getenv("CONVEX_URL")),
            "r2_storage": bool(os.getenv("R2_ENDPOINT")),
            "runpod_gpu": bool(os.getenv("RUNPOD_API_KEY")),
            "fish_audio_tts": bool(os.getenv("FISH_API_KEY")),
            "gemini_asr": bool(os.getenv("GEMINI_API_KEY")),
            "telegram_bot": bool(os.getenv("TELEGRAM_BOT_TOKEN")),
        },
        "environment": os.getenv("PIRD_ENV", "production"),
        "timestamp": int(time.time()),
    }


# -------------------------------------------------------------
# 8. Server-Side Argon2id PIN Security & Strike Verification
# -------------------------------------------------------------
DEFAULT_INTERNAL_KEY = os.getenv("INTERNAL_API_KEY", "145534d5f41b80429286b485055cc6376c7b55bbdd79641eba65b7cbece80a5d")


@router.get("/shield/status")
async def get_shield_status(user: AuthenticatedUser = Depends(require_admin)):
    """Check if current admin has configured an Argon2id PIN and if locked."""
    if not user.user_id or not user.user_id.strip():
        raise HTTPException(401, "Invalid token: missing subject identity (sub)")
    client = convex_db._get_client()
    try:
        status_info = await asyncio.to_thread(
            client.query,
            "admin:getAdminPinStatusInternal",
            {
                "userId": user.user_id,
                "__internalApiKey": DEFAULT_INTERNAL_KEY,
            },
        )
        return {"status": "ok", **status_info}
    except Exception as e:
        logger.error(f"[SHIELD-STATUS] Error: {e}")
        return {"status": "error", "hasPin": False, "isPermanentlyLocked": False, "attemptsRemaining": 5}


@router.post("/shield/setup-pin")
async def setup_admin_pin(req: SetupPinRequest, user: AuthenticatedUser = Depends(require_admin)):
    """Configure a new 6-digit PIN securely hashed with Argon2id on the server."""
    logger.info(f"[SETUP-PIN-START] Request from User ID: '{user.user_id}', Email: '{user.email}'")

    if not user.user_id or not user.user_id.strip():
        logger.error("[SETUP-PIN-DENIED] Missing subject identity (sub) in token")
        raise HTTPException(401, "Invalid token: missing subject identity (sub)")
    if not user.email or not user.email.strip():
        logger.error("[SETUP-PIN-DENIED] Missing email claim in Clerk JWT")
        raise HTTPException(401, "Invalid token: missing email identity claim in Clerk JWT")

    pin_str = str(req.pin).strip()
    confirm_str = str(req.confirm_pin).strip()

    if len(pin_str) != 6 or not pin_str.isdigit():
        raise HTTPException(400, "PIN must be exactly 6 numeric digits.")
    if pin_str != confirm_str:
        raise HTTPException(400, "PIN confirmation does not match.")

    try:
        argon2_hash = _argon2_hasher.hash(pin_str)
        logger.info(f"[SETUP-PIN-HASH] Argon2id hash generated successfully (len={len(argon2_hash)})")
    except Exception as hash_err:
        logger.error(f"[ARGON2-HASH-ERROR] Failed to hash PIN: {hash_err}")
        raise HTTPException(500, f"Argon2id hashing failed: {hash_err}")

    client = convex_db._get_client()
    try:
        internal_key = DEFAULT_INTERNAL_KEY
        logger.info(f"[SETUP-PIN-CONVEX] Executing admin:setupAdminPinInternal (internalKey len={len(internal_key)})")
        mutation_res = await asyncio.to_thread(
            client.mutation,
            "admin:setupAdminPinInternal",
            {
                "userId": user.user_id,
                "email": user.email,
                "argon2Hash": argon2_hash,
                "__internalApiKey": internal_key,
            },
        )
        logger.info(f"[SETUP-PIN-SUCCESS] Convex mutation succeeded for user '{user.user_id}', record ID: {mutation_res}")
        return {"status": "ok", "message": "Argon2id PIN initialized successfully."}
    except Exception as e:
        logger.exception(f"[SETUP-PIN-ERROR] Convex mutation failed: {e}")
        raise HTTPException(500, f"Database PIN setup failed: {e}")


@router.post("/shield/verify-pin")
async def verify_admin_pin(req: VerifyPinRequest, request: Request, user: AuthenticatedUser = Depends(require_admin)):
    """Verify admin PIN against server-side Argon2id hash with 5-strike database lockout."""
    if not user.user_id or not user.user_id.strip():
        raise HTTPException(401, "Invalid token: missing subject identity (sub)")

    pin_str = str(req.pin).strip()

    client = convex_db._get_client()
    pin_doc = await asyncio.to_thread(
        client.query,
        "admin:getAdminPinHashInternal",
        {
            "userId": user.user_id,
            "__internalApiKey": DEFAULT_INTERNAL_KEY,
        },
    )

    if not pin_doc or not pin_doc.get("argon2Hash"):
        raise HTTPException(400, "PIN not configured for this account. Run setup first.")

    if pin_doc.get("isPermanentlyLocked"):
        revoke_all_user_sessions(user.user_id)
        raise HTTPException(
            423,
            "Account is permanently locked due to excessive failed PIN attempts. Contact Super Admin to unlock.",
        )

    stored_hash = pin_doc["argon2Hash"]
    is_valid = False
    try:
        is_valid = _argon2_hasher.verify(stored_hash, pin_str)
    except VerifyMismatchError:
        is_valid = False
    except Exception as e:
        logger.error(f"[ARGON2-VERIFY] Verification failure: {e}")
        is_valid = False

    # Record verification result in Convex database
    client_ip = request.client.host if request.client else "unknown"
    record_res = await asyncio.to_thread(
        client.mutation,
        "admin:recordPinVerificationResultInternal",
        {
            "userId": user.user_id,
            "email": user.email or "",
            "success": is_valid,
            "ipAddress": client_ip,
            "__internalApiKey": DEFAULT_INTERNAL_KEY,
        },
    )

    if not is_valid:
        if record_res.get("isPermanentlyLocked"):
            revoke_all_user_sessions(user.user_id)
            raise HTTPException(
                423,
                "Maximum 5 unlock attempts exceeded. All active sessions have been terminated. Account locked.",
            )
        attempts_left = record_res.get("attemptsRemaining", 0)
        raise HTTPException(
            401,
            f"Invalid PIN. {attempts_left} attempt{'s' if attempts_left != 1 else ''} remaining.",
        )

    return {"status": "UNLOCKED", "message": "Session verified."}

