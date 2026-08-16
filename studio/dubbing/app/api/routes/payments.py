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
    is_chargeback: Optional[bool] = False


from pydantic import BaseModel, field_validator


class WaylWebhookPayload(BaseModel):
    referenceId: Optional[str] = None
    reference_id: Optional[str] = None
    status: Optional[str] = None
    amount: Optional[int] = None
    total: Optional[int] = None
    currency: Optional[str] = "IQD"
    env: Optional[str] = None
    tier_id: Optional[str] = None
    workspace_id: Optional[str] = None

    @field_validator("amount", "total", mode="before")
    @classmethod
    def validate_integer_only(cls, v):
        if v is not None:
            if isinstance(v, float):
                raise ValueError("Floating-point amounts strictly rejected; integer minor units required.")
            if isinstance(v, str):
                try:
                    int_val = int(v)
                    return int_val
                except ValueError:
                    raise ValueError(f"Invalid integer amount string: {v}")
        return v


MAX_BODY_BYTES = 64 * 1024  # 64 KB cap for Wayl webhooks


def log_security_event(event_type: str, **kwargs):
    logger.warning(json.dumps({
        "security_event": event_type,
        "service": "payments",
        **kwargs
    }))


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
    links = await wayl.list_links()
    refunds = await wayl.list_refunds()
    
    return {
        "links": [
            {
                "id": l.get("id"),
                "referenceId": l.get("referenceId"),
                "status": l.get("status"),
                "amount": l.get("amount"),
                "currency": l.get("currency"),
                "createdAt": l.get("createdAt")
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
                amount_val = int(float(l.get("amount", 1000) or 1000))
                currency_val = str(l.get("currency", "IQD"))
                await database.record_and_process_wayl_event(
                    client,
                    reference_id=ref_id,
                    amount=amount_val,
                    currency=currency_val,
                    raw_payload=json.dumps(l)
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
                
    return {
        "status": "synchronized",
        "synced_paid_count": synced_paid,
        "synced_refund_count": synced_refunds
    }


@router.post("/checkout")
async def create_checkout(
    req: CheckoutRequest,
    user: AuthenticatedUser = Depends(require_user)
):
    """Generate a secure Wayl hosted checkout link for a workspace."""
    if req.tier not in TIERS:
        raise HTTPException(status_code=400, detail=f"Invalid tier: {req.tier}. Allowed: {list(TIERS.keys())}")

    tier_info = TIERS[req.tier]
    usd_amount = float(tier_info["price_usd"])
    minutes = int(tier_info["minutes"])

    try:
        usd_to_iqd_rate = float(os.getenv("USD_TO_IQD_RATE", "1500"))
    except ValueError:
        usd_to_iqd_rate = 1500.0

    if "fixed_iqd" in tier_info:
        total_iqd = int(tier_info["fixed_iqd"])
    else:
        total_iqd = int(round(usd_amount * usd_to_iqd_rate))

    reference_id = f"ref_{uuid.uuid4().hex}"

    base_redirect = os.getenv("WAYL_REDIRECT_BASE_URL", "").strip()
    if not base_redirect or "localhost" in base_redirect:
        base_redirect = "https://doblaj.com/billing"
    redirection_url = f"{base_redirect}?payment=success&ref={reference_id}"

    try:
        client = _get_service_role_client()

        # Layer 10: Quarantine / Chargeback Lockdown Check
        ws = await database.get_workspace_details(client, workspace_id=user.workspace_id)
        if ws and (ws.get("status") in ("under_review", "LOCKED_REFUND", "RESTRICTED_VELOCITY") or ws.get("isLocked") is True):
            log_security_event("quarantined_workspace_checkout_rejected", workspace_id=user.workspace_id)
            raise HTTPException(status_code=403, detail="Workspace is under review due to risk/chargeback. Checkout creation disabled.")

        # Layer 3 & 4: Record expected charge before link issuance
        await database.record_expected_charge(
            client,
            reference_id=reference_id,
            workspace_id=user.workspace_id,
            amount=total_iqd,
            currency="IQD",
            minutes_granted=minutes,
            tier=req.tier
        )

        wayl = WaylClient()
        checkout_url = await wayl.create_payment_link(
            reference_id=reference_id,
            amount_iqd=total_iqd,
            redirection_url=redirection_url,
            item_label=f"Doblaj ({minutes} min) - ${usd_amount:.2f} USD ({total_iqd:,} IQD)"
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

    workspace_id = None
    try:
        workspace_id = await database.get_workspace_by_telegram_id(req.telegram_chat_id)
    except Exception as e:
        logger.warning(f"[PAYMENTS_TG] Could not lookup workspace by telegram ID: {e}")

    if not workspace_id:
        workspace_id = f"tg_{req.telegram_chat_id}"

    reference_id = f"ref_tg_{req.telegram_chat_id}_{uuid.uuid4().hex[:8]}"

    base_redirect = os.getenv("DUBBING_FRONTEND_URL", "https://doblaj.com").strip()
    redirection_url = f"{base_redirect.rstrip('/')}/dubbing?payment=success&ref={reference_id}"

    client = _get_service_role_client()
    try:
        # Layer 3 & 4: Persist expected charge
        await database.record_expected_charge(
            client,
            reference_id=reference_id,
            workspace_id=workspace_id,
            amount=total_iqd,
            currency="IQD",
            minutes_granted=minutes,
            tier=tier_name
        )
    except Exception as tx_e:
        logger.warning(f"[PAYMENTS_TG] record_expected_charge notice: {tx_e}")

    wayl = WaylClient()
    try:
        checkout_url = await wayl.create_payment_link(
            reference_id=reference_id,
            amount_iqd=total_iqd,
            redirection_url=redirection_url,
            expires_in=req.expires_in or "30m",
            item_label=f"Doblaj ({minutes} min) - ${usd_amount:.2f} USD ({total_iqd:,} IQD)"
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
    """Receive payment webhook from Wayl with strict 12-layer security enforcement.
    
    1. Cap raw body size at 64KB (Layer 3: 413 on payload too large).
    2. HMAC-SHA256 constant-time verification over raw bytes (Layer 3: 401 on bad signature).
    3. Pydantic schema validation post-signature (Layer 3: 400 on malformed structure).
    4. Atomic single Convex mutation with Read-First Zero-Cost Idempotency (Layer 4).
    """
    # 1. Cap raw body size
    raw_body = await request.body()
    if len(raw_body) > MAX_BODY_BYTES:
        log_security_event("webhook_payload_too_large", raw_len=len(raw_body))
        raise HTTPException(status_code=413, detail="Payload Too Large")

    # 2. Extract signature header & verify
    signature = (
        request.headers.get("x-wayl-signature-256") or 
        request.headers.get("X-Wayl-Signature-256")
    )
    
    if not signature:
        log_security_event("webhook_missing_signature", ip=request.client.host if request.client else "unknown")
        raise HTTPException(status_code=401, detail="Missing signature header")

    wayl = WaylClient()
    if not wayl.verify_webhook_signature(raw_body, signature):
        log_security_event("webhook_bad_signature", ip=request.client.host if request.client else "unknown")
        raise HTTPException(status_code=401, detail="Invalid signature")

    # 3. Post-signature schema validation
    try:
        payload_dict = json.loads(raw_body.decode('utf-8'))
        event = WaylWebhookPayload.model_validate(payload_dict)
    except Exception as parse_e:
        log_security_event("webhook_bad_schema", error=str(parse_e), raw_len=len(raw_body))
        raise HTTPException(status_code=400, detail="Invalid JSON schema")

    reference_id = event.referenceId or event.reference_id
    if not reference_id:
        raise HTTPException(status_code=400, detail="Missing referenceId in payload")

    # Layer 1.2: Environment Confusion Defense
    server_env = os.getenv("WAYL_SERVER_ENV", os.getenv("PIRD_ENV", "dev")).lower()
    if server_env in ("live", "production", "prod") and event.env in ("test", "sandbox"):
        log_security_event("environment_confusion_rejected", server_env=server_env, event_env=event.env)
        raise HTTPException(status_code=401, detail="Environment mismatch: test payment rejected on production")

    event_status = event.status or ""
    amount = event.amount or event.total or 1000
    currency = event.currency or "IQD"

    client = _get_service_role_client()

    # 4. Handle Complete Status via Single Convex Mutation
    if event_status == "Complete":
        raw_text = raw_body.decode('utf-8', errors='ignore')
        res = await database.record_and_process_wayl_event(
            client,
            reference_id=reference_id,
            amount=int(amount),
            currency=currency,
            raw_payload=raw_text
        )
        
        status_val = res.get("status") if isinstance(res, dict) else ""
        if status_val == "already_processed":
            logger.warning(f"[WAYL_WEBHOOK] Replay / duplicate event for referenceId={reference_id}. Returning 200 OK without re-crediting.")
            return {"status": "ok", "message": "Transaction already processed"}
        elif status_val == "flagged":
            log_security_event("payment_flagged_for_review", reference_id=reference_id, reason=res.get("reason"))
            return {"status": "ok", "message": "Payment flagged for review"}
        else:
            logger.info(f"[WAYL_WEBHOOK] Payment Complete processed atomically for referenceId={reference_id}")
            return {"status": "ok", "result": res}

    # 5. Handle Refund / Return
    if event_status in ("Refunded", "Returned"):
        res = await database.process_refund_atomic(
            client,
            transaction_id=reference_id,
            workspace_id="",
            reason="Gateway Refund Notification",
            is_chargeback=False
        )
        return {"status": "ok", "result": res}

    return {"status": "ok", "message": f"Status {event_status} acknowledged"}


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
        
        client = _get_service_role_client()
        amount_usd = round(req.amount_iqd / 1500.0, 2)
        minutes_to_deduct = 1 if req.amount_iqd <= 2000 else (5 if req.amount_iqd <= 15000 else (15 if req.amount_iqd <= 30000 else 120))
        
        await database.process_refund_atomic(
            client,
            transaction_id=req.reference_id,
            workspace_id=user.workspace_id,
            amount_usd=amount_usd,
            minutes_deducted=minutes_to_deduct,
            reason=req.reason,
            is_chargeback=req.is_chargeback or False
        )
        
        return {
            "status": "refunded",
            "reference_id": req.reference_id,
            "wayl_response": res
        }
    except Exception as e:
        logger.exception("[WAYL_REFUND] Refund failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Refund failed: {str(e)}")
