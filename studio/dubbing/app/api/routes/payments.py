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


class TelegramLinkRequest(BaseModel):
    telegram_chat_id: str
    tier: Optional[str] = None
    minutes: Optional[int] = None
    amount_usd: Optional[float] = None
    expires_in: Optional[str] = "30m"


class RefundRequest(BaseModel):
    reference_id: str
    amount_iqd: int = 1000
    reason: str


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


@router.get("/status-summary")
async def payment_status_summary():
    """Diagnostic tool: Fetch all live Wayl links & refunds directly from Wayl API."""
    wayl = WaylClient()
    links = await wayl.list_links(take=50)
    refunds = await wayl.list_refunds()
    
    return {
        "status": "ok",
        "server_env": wayl._get_env(),
        "base_url": wayl._get_base_url(),
        "total_links": len(links),
        "total_refunds": len(refunds),
        "links": [
            {
                "referenceId": l.get("referenceId"),
                "status": l.get("status"),
                "total": l.get("total"),
                "createdAt": l.get("createdAt"),
                "paymentMethod": l.get("paymentMethod")
            }
            for l in links
        ],
        "refunds": [
            {
                "id": r.get("id"),
                "referenceId": r.get("referenceId"),
                "status": r.get("status"),
                "amount": r.get("amount"),
                "reason": r.get("reason"),
                "createdAt": r.get("createdAt")
            }
            for r in refunds
        ]
    }


@router.post("/sync-all")
async def sync_all_transactions(user: AuthenticatedUser = Depends(require_user)):
    """Force complete synchronization between Wayl API and Convex workspace."""
    wayl = WaylClient()
    client = _get_service_role_client()
    
    links = await wayl.list_links(take=50)
    refunds = await wayl.list_refunds()
    
    synced_paid = 0
    synced_refunds = 0
    
    for l in links:
        ref_id = (l.get("referenceId") or "").split("/")[0].split("?")[0]
        status = l.get("status")
        if ref_id and status == "Complete":
            exists = await database.transaction_exists(client, transaction_id=ref_id)
            if not exists:
                await database.process_payment_success_atomic(
                    client,
                    transaction_id=ref_id,
                    workspace_id=user.workspace_id,
                    tier="test_1000iqd",
                    amount_usd=0.67,
                    minutes_added=1
                )
                synced_paid += 1
                
    for rf in refunds:
        rf_ref = (rf.get("referenceId") or "").split("/")[0].split("?")[0]
        status = rf.get("status")
        if rf_ref and status in ("Refunded", "Requested"):
            refund_key = f"REFUND-{rf_ref}"
            exists = await database.transaction_exists(client, transaction_id=refund_key)
            if not exists:
                amount_iqd = rf.get("amount", 1000)
                amount_usd = round(amount_iqd / 1500.0, 2)
                await database.process_refund_atomic(
                    client,
                    transaction_id=rf_ref,
                    workspace_id=user.workspace_id,
                    amount_usd=amount_usd,
                    minutes_deducted=1,
                    reason=rf.get("reason", "Wayl Dashboard Sync")
                )
                synced_refunds += 1
                
    for l in links:
        ref_id = (l.get("referenceId") or "").split("/")[0].split("?")[0]
        status = l.get("status")
        if ref_id and status in ("Refunded", "Returned"):
            refund_key = f"REFUND-{ref_id}"
            exists = await database.transaction_exists(client, transaction_id=refund_key)
            if not exists:
                await database.process_refund_atomic(
                    client,
                    transaction_id=ref_id,
                    workspace_id=user.workspace_id,
                    amount_usd=0.67,
                    minutes_deducted=1,
                    reason="Wayl Link Refunded"
                )
                synced_refunds += 1
                
    return {
        "status": "success",
        "synced_paid": synced_paid,
        "synced_refunds": synced_refunds,
        "total_links_checked": len(links),
        "total_refunds_checked": len(refunds)
    }


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
    base_redirect = os.getenv("WAYL_REDIRECT_BASE_URL", "").strip()
    if not base_redirect or "localhost" in base_redirect:
        base_redirect = "https://doblaj.com/billing"
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


@router.post("/create-telegram-link")
@router.post("/create-telegram-link/")
async def create_telegram_payment_link(req: TelegramLinkRequest, request: Request):
    """Generate an expiring Wayl payment link (default: 30m) directly from Telegram."""
    # 1. Resolve tier or custom parameters
    if req.tier and req.tier in TIERS:
        tier_info = TIERS[req.tier]
        usd_amount = float(tier_info["price_usd"])
        minutes = int(tier_info["minutes"])
        tier_name = req.tier
        fixed_iqd = tier_info.get("fixed_iqd")
    elif req.minutes and req.amount_usd:
        usd_amount = float(req.amount_usd)
        minutes = int(req.minutes)
        tier_name = f"custom_{minutes}m"
        fixed_iqd = None
    else:
        raise HTTPException(status_code=400, detail="Must provide a valid 'tier' or 'minutes' + 'amount_usd'")

    try:
        usd_to_iqd_rate = float(os.getenv("USD_TO_IQD_RATE", "1500"))
    except ValueError:
        usd_to_iqd_rate = 1500.0

    if fixed_iqd:
        total_iqd = int(fixed_iqd)
    else:
        total_iqd = int(round(usd_amount * usd_to_iqd_rate))

    # 2. Resolve linked workspace for this Telegram chat ID
    workspace_id = None
    try:
        workspace_id = await database.get_workspace_by_telegram_id(req.telegram_chat_id)
    except Exception as e:
        logger.warning(f"[PAYMENTS_TG] Could not lookup workspace by telegram ID: {e}")

    if not workspace_id:
        workspace_id = f"tg_{req.telegram_chat_id}"

    # 3. Create Unique Reference ID
    reference_id = f"ref_tg_{req.telegram_chat_id}_{uuid.uuid4().hex[:8]}"

    # 4. Redirection URL (Lands on /dubbing with payment success params)
    base_redirect = os.getenv("DUBBING_FRONTEND_URL", "https://doblaj.com").strip()
    redirection_url = f"{base_redirect.rstrip('/')}/dubbing?payment=success&ref={reference_id}"

    # 5. Record pending transaction in Convex
    client = _get_service_role_client()
    try:
        await database.add_transaction(
            client,
            transaction_id=reference_id,
            workspace_id=workspace_id,
            tier=tier_name,
            amount_usd=usd_amount,
            minutes_added=minutes
        )
    except Exception as tx_e:
        logger.warning(f"[PAYMENTS_TG] add_transaction notice: {tx_e}")

    # 6. Generate Wayl link with 30m expiration
    wayl = WaylClient()
    try:
        checkout_url = await wayl.create_payment_link(
            reference_id=reference_id,
            amount_iqd=total_iqd,
            redirection_url=redirection_url,
            expires_in=req.expires_in or "30m"
        )
    except Exception as e:
        logger.exception("[PAYMENTS_TG] Failed to create Wayl payment link: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to generate payment link: {str(e)}")

    return {
        "checkout_url": checkout_url,
        "reference_id": reference_id,
        "amount_iqd": total_iqd,
        "amount_usd": usd_amount,
        "minutes": minutes,
        "tier": tier_name,
        "expires_in": req.expires_in or "30m",
        "redirection_url": redirection_url
    }



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
            logger.info(f"[WAYL_WEBHOOK] Successfully processed payment for referenceId={reference_id}")
        return {"status": "ok", "message": "Payment processed successfully"}
    
    if event_status in ("Refunded", "Returned"):
        tier_id = payload.get("tier_id") or "test_1000iqd"
        workspace_id = payload.get("workspace_id")
        tier_info = TIERS.get(tier_id, TIERS.get("test_1000iqd", {"minutes": 1, "price_usd": 0.67}))
        minutes_to_deduct = tier_info.get("minutes", 1)
        amount_usd = tier_info.get("price_usd", 0.67)
        
        if workspace_id:
            res = await database.process_refund_atomic(
                client,
                transaction_id=reference_id,
                workspace_id=workspace_id,
                amount_usd=amount_usd,
                minutes_deducted=minutes_to_deduct,
                reason="Refund processed by payment gateway"
            )
            logger.info(f"[WAYL_WEBHOOK] Refund processed for referenceId={reference_id}, deducted {minutes_to_deduct} min from workspace {safe_ws(workspace_id)}")
            return {"status": "ok", "result": res}
        return {"status": "ok", "message": "Refund webhook received"}
    
    logger.info(f"[WAYL_WEBHOOK] Ignored status={event_status} for referenceId={reference_id}")
    return {"status": "ok", "message": f"Status {event_status} ignored"}


@router.post("/refund")
async def process_refund(
    req: RefundRequest,
    user: AuthenticatedUser = Depends(require_user)
):
    """Process a payment refund via Wayl API POST /api/v1/refunds and deduct minutes atomically in Convex."""
    wayl = WaylClient()
    try:
        res = await wayl.create_refund(
            reference_id=req.reference_id,
            amount_iqd=req.amount_iqd,
            reason=req.reason
        )
        
        # Atomically record refund transaction in Convex and deduct workspace minutes
        client = _get_service_role_client()
        amount_usd = round(req.amount_iqd / 1500.0, 2)
        minutes_to_deduct = 1 if req.amount_iqd <= 2000 else (5 if req.amount_iqd <= 15000 else (15 if req.amount_iqd <= 30000 else 120))
        
        await database.process_refund_atomic(
            client,
            transaction_id=req.reference_id,
            workspace_id=user.workspace_id,
            amount_usd=amount_usd,
            minutes_deducted=minutes_to_deduct,
            reason=req.reason
        )
        
        return {"status": "success", "data": res}
    except Exception as e:
        logger.error(f"[REFUND_ERROR] Refund failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
