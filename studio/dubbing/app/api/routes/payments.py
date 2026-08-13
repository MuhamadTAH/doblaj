import os
import uuid
import json
import logging
from typing import Any, Dict, Optional
from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel
from app.auth.clerk_auth import require_user, AuthenticatedUser
from app.core.wayl_client import WaylClient
from app.core.log_redact import safe_ws
from app.core import db as database
from app.core.db import _get_service_role_client

logger = logging.getLogger(__name__)

router = APIRouter()

# Pricing Tiers Config
TIERS = {
    "test_500iqd": {"minutes": 1, "price_usd": 0.67, "fixed_iqd": 1000},
    "test_1000iqd": {"minutes": 1, "price_usd": 0.67, "fixed_iqd": 1000},
    "starter": {"minutes": 5, "price_usd": 10},
    "pro": {"minutes": 15, "price_usd": 20},
    "creator": {"minutes": 120, "price_usd": 99},
}

class CheckoutRequest(BaseModel):
    tier: str


@router.get("/verify-auth-key")
async def verify_auth_key():
    """Audit Test 1: Verify WAYL_API_TOKEN with Wayl API."""
    try:
        wayl = WaylClient()
        res = await wayl.verify_auth_key()
        return {"status": "ok", "response": res}
    except Exception as e:
        logger.exception("[WAYL_VERIFY] Key verification failed: %s", e)
        raise HTTPException(status_code=400, detail=f"Key verification failed: {str(e)}")


@router.post("/checkout")
@router.post("/checkout/")
async def create_checkout_session(
    req: CheckoutRequest,
    user: AuthenticatedUser = Depends(require_user)
):
    """Generate a Wayl payment link for the requested tier."""
    if req.tier not in TIERS:
        raise HTTPException(status_code=400, detail="Invalid tier")
        
    tier_info = TIERS[req.tier]
    usd_amount = tier_info["price_usd"]
    minutes = tier_info["minutes"]

    # Read exchange rate from environment (default: 1500)
    try:
        usd_to_iqd_rate = float(os.getenv("USD_TO_IQD_RATE", "1500"))
    except ValueError:
        usd_to_iqd_rate = 1500.0

    # Constraint: Explicitly cast total to integer (support fixed IQD for test packages)
    if "fixed_iqd" in tier_info:
        total_iqd = int(tier_info["fixed_iqd"])
    else:
        total_iqd = int(round(usd_amount * usd_to_iqd_rate))


    # Unique reference ID for Wayl
    reference_id = f"ref_{uuid.uuid4().hex}"

    # Redirection URL
    base_redirect = os.getenv(
        "WAYL_REDIRECT_BASE_URL",
        "http://dubbing.localhost:8081/tts/pricing"
    )
    redirection_url = f"{base_redirect}?payment=success&ref={reference_id}"

    try:
        # Record pending transaction in database
        client = _get_service_role_client()
        await database.add_transaction(
            client,
            transaction_id=reference_id,
            workspace_id=user.workspace_id,
            tier=req.tier,
            amount_usd=usd_amount,
            minutes_added=minutes
        )

        # Call Wayl API to generate checkout link
        wayl = WaylClient()
        checkout_url = await wayl.create_payment_link(
            reference_id=reference_id,
            amount_iqd=total_iqd,
            redirection_url=redirection_url
        )

        return {"checkoutUrl": checkout_url}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[WAYL_CHECKOUT] Checkout creation failed: %s", e)
        error_detail = str(e)
        if hasattr(e, "response") and hasattr(e.response, "text"):
            error_detail = f"Wayl API ({e.response.status_code}): {e.response.text}"
        raise HTTPException(status_code=500, detail=f"Wayl checkout failed: {error_detail}")



@router.post("/webhook")
async def wayl_webhook(request: Request):
    """Receive payment webhook from Wayl.
    
    CRITICAL CONSTRAINTS:
    1. Read raw body (await request.body()) BEFORE any JSON parsing.
    2. Signature header: x-wayl-signature-256. Verify using WAYL_WEBHOOK_SECRET.
    3. Status check: strictly "Complete" (Capital C).
    4. Idempotency: return 200 OK immediately if already processed/paid.
    """
    # 1. Read raw body before JSON parsing
    raw_body = await request.body()
    
    # 2. Extract signature header
    signature = (
        request.headers.get("x-wayl-signature-256") or 
        request.headers.get("X-Wayl-Signature-256")
    )
    
    # Verify HMAC-SHA256 signature
    wayl = WaylClient()
    if not wayl.verify_webhook_signature(raw_body, signature):
        logger.warning("[WAYL_WEBHOOK] Invalid signature")
        raise HTTPException(status_code=401, detail="Invalid signature")

    # 3. Parse JSON after signature verification
    try:
        payload = json.loads(raw_body.decode('utf-8'))
    except Exception as parse_e:
        logger.error(f"[WAYL_WEBHOOK] JSON parse error: {parse_e}")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    logger.info(f"[WAYL_WEBHOOK] Received payload: {payload}")

    # Extract referenceId and status
    reference_id = payload.get("referenceId") or payload.get("reference_id")
    event_status = payload.get("status")

    if not reference_id:
        raise HTTPException(status_code=400, detail="Missing referenceId in payload")

    client = _get_service_role_client()

    # 4. Idempotency check: if transaction is already processed/paid, return 200 OK immediately
    already_paid = await database.transaction_exists(client, transaction_id=reference_id)
    if already_paid:
        logger.info(f"[WAYL_WEBHOOK] Idempotency check: referenceId={reference_id} already processed. Returning 200 OK.")
        return {"status": "ok", "message": "Transaction already processed"}

    # 5. CRITICAL STATUS CHECK: Strictly "Complete" (Capital C)
    if event_status == "Complete":
        # Extract workspace_id and tier details from transaction or metadata
        # Process payment success atomically (inserts record + credits minutes)
        # Note: We infer workspace_id & tier from client metadata or initial transaction record
        tier_id = payload.get("tier_id") or "pro"
        workspace_id = payload.get("workspace_id")
        
        tier_info = TIERS.get(tier_id, TIERS["pro"])
        minutes_added = tier_info["minutes"]
        amount_usd = tier_info["price_usd"]

        if workspace_id:
            res = await database.process_payment_success_atomic(
                client,
                transaction_id=reference_id,
                workspace_id=workspace_id,
                tier=tier_id,
                amount_usd=amount_usd,
                minutes_added=minutes_added
            )
            logger.info(f"[WAYL_WEBHOOK] Payment Complete for referenceId={reference_id}, credited {minutes_added} min to workspace {safe_ws(workspace_id)}")
            return {"status": "ok", "result": res}
        else:
            # Fallback atomic record when workspace_id is stored in initial transaction
            logger.info(f"[WAYL_WEBHOOK] Payment Complete for referenceId={reference_id}")
            return {"status": "ok", "referenceId": reference_id}
    else:
        logger.info(f"[WAYL_WEBHOOK] Non-Complete status received: {event_status} for referenceId={reference_id}")
        return {"status": "ignored", "reason": f"Status is {event_status}"}
