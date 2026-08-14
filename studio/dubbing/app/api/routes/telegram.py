import os
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
from app.auth.clerk_auth import require_user, require_user_or_internal, AuthenticatedUser
from app.core import database as db
from app.core import database_convex as convex_db
import logging
import uuid

logger = logging.getLogger(__name__)

router = APIRouter()

class LinkNonceResponse(BaseModel):
    nonce: str
    expires_in_minutes: int

class LinkVerifyRequest(BaseModel):
    nonce: str
    telegram_chat_id: str

class JobReserveRequest(BaseModel):
    telegram_chat_id: str
    video_duration_seconds: int

class JobReserveResponse(BaseModel):
    reservation_id: str
    workspace_id: str
    minutes_reserved: int

class JobRefundRequest(BaseModel):
    reservation_id: str
    telegram_chat_id: str
    minutes_to_refund: int


@router.post("/link-nonce", response_model=LinkNonceResponse)
@router.post("/link-nonce/", response_model=LinkNonceResponse, include_in_schema=False)
async def generate_link_nonce(user: AuthenticatedUser = Depends(require_user)):
    """Generate a short-lived nonce for linking a Telegram account to the user's workspace."""
    expires_in = 10
    nonce = await db.create_telegram_nonce(user.workspace_id, expires_in)
    return LinkNonceResponse(nonce=nonce, expires_in_minutes=expires_in)


@router.post("/link-verify")
async def verify_link_nonce(req: LinkVerifyRequest, user: AuthenticatedUser = Depends(require_user_or_internal)):
    """Consume a nonce and link the provided telegram chat ID to the workspace."""
    if user.email != "bot@internal.doblaj.com":
        raise HTTPException(status_code=403, detail="Only internal bot can call this endpoint.")
        
    workspace_id = await db.consume_telegram_nonce(req.nonce)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="Invalid or expired nonce.")
        
    success = await db.link_telegram_account(req.telegram_chat_id, workspace_id)
    if not success:
        raise HTTPException(status_code=409, detail="This workspace is already linked to another Telegram account.")
        
    return {"status": "success", "workspace_id": workspace_id}


MAX_RESERVATION_SECONDS = int(os.getenv("MAX_RESERVATION_SECONDS", "1800"))

@router.post("/jobs/reserve", response_model=JobReserveResponse)
async def reserve_job_minutes(req: JobReserveRequest, user: AuthenticatedUser = Depends(require_user_or_internal)):
    """Reserve minutes for a job upfront."""
    if user.email != "bot@internal.doblaj.com":
        raise HTTPException(status_code=403, detail="Only internal bot can call this endpoint.")

    if req.video_duration_seconds <= 0:
        raise HTTPException(status_code=400, detail="video_duration_seconds must be > 0")
    if req.video_duration_seconds > MAX_RESERVATION_SECONDS:
        raise HTTPException(status_code=400, detail=f"video_duration_seconds exceeds maximum allowed limit of {MAX_RESERVATION_SECONDS}s ({MAX_RESERVATION_SECONDS // 60} mins)")

    workspace_id = await db.get_workspace_by_telegram_id(req.telegram_chat_id)
    if not workspace_id:
        raise HTTPException(status_code=404, detail="Telegram account not linked to any workspace.")
        
    # Calculate required minutes: ceiling of duration / 60
    import math
    required_minutes = math.ceil(req.video_duration_seconds / 60.0)
    if required_minutes <= 0:
        required_minutes = 1  # Minimum 1 minute charge
        
    # Check if user has enough minutes (this could be racy, but deduct_workspace_minutes is atomic in Convex)
    current_minutes = await convex_db.get_workspace_minutes(workspace_id=workspace_id)
    if current_minutes < required_minutes:
        raise HTTPException(status_code=402, detail=f"Insufficient minutes. Required: {required_minutes}, Available: {current_minutes}")
        
    # Deduct minutes via Convex
    await convex_db.deduct_workspace_minutes(workspace_id=workspace_id, minutes=required_minutes)
    
    # Generate a reservation ID (the bot can use this as a job ID if it wants)
    reservation_id = str(uuid.uuid4())
    
    return JobReserveResponse(
        reservation_id=reservation_id,
        workspace_id=workspace_id,
        minutes_reserved=required_minutes
    )


@router.post("/jobs/refund")
async def refund_job_minutes(req: JobRefundRequest, user: AuthenticatedUser = Depends(require_user_or_internal)):
    """Refund minutes if the job failed before or during submission to backend."""
    if user.email != "bot@internal.doblaj.com":
        raise HTTPException(status_code=403, detail="Only internal bot can call this endpoint.")

    if req.minutes_to_refund <= 0:
        raise HTTPException(status_code=400, detail="minutes_to_refund must be > 0")
    if req.minutes_to_refund > 30:
        raise HTTPException(status_code=400, detail="minutes_to_refund exceeds maximum single refund limit of 30 minutes.")

    workspace_id = await db.get_workspace_by_telegram_id(req.telegram_chat_id)
    if not workspace_id:
        raise HTTPException(status_code=404, detail="Telegram account not linked to any workspace.")
        
    # Refund minutes via Convex
    await convex_db.add_workspace_minutes(workspace_id=workspace_id, minutes=req.minutes_to_refund)
    return {"status": "ok", "refunded_minutes": req.minutes_to_refund, "workspace_id": workspace_id}


@router.get("/balance/{telegram_chat_id}")
async def get_telegram_user_balance(telegram_chat_id: str):
    """Retrieve remaining minutes balance for a Telegram user."""
    workspace_id = await db.get_workspace_by_telegram_id(telegram_chat_id)
    if not workspace_id:
        return {
            "is_linked": False,
            "remaining_minutes": 0,
            "workspace_id": None,
            "message": "Account not linked to a Doblaj workspace"
        }
        
    try:
        minutes = await convex_db.get_workspace_minutes(workspace_id=workspace_id)
        return {
            "is_linked": True,
            "remaining_minutes": int(minutes),
            "workspace_id": workspace_id
        }
    except Exception as e:
        logger.error(f"[TELEGRAM_BALANCE] Error getting minutes for {workspace_id}: {e}")
        return {
            "is_linked": True,
            "remaining_minutes": 0,
            "workspace_id": workspace_id,
            "error": str(e)
        }
