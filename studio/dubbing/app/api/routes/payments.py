import logging
from typing import Any, Dict
from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel
from app.auth.clerk_auth import require_user, AuthenticatedUser
from app.core.suby_client import SubyClient
from app.core.log_redact import safe_ws
import os

logger = logging.getLogger(__name__)

router = APIRouter()

# Pricing Tiers Config
TIERS = {
    "starter": {"minutes": 5, "price_usd": 10},
    "pro": {"minutes": 15, "price_usd": 20},
    "creator": {"minutes": 120, "price_usd": 99},
}

class CheckoutRequest(BaseModel):
    tier: str

@router.post("/checkout")
async def create_checkout_session(req: CheckoutRequest, user: AuthenticatedUser = Depends(require_user)):
    """Generate a Suby checkout URL for the requested tier."""
    if req.tier not in TIERS:
        raise HTTPException(status_code=400, detail="Invalid tier")
        
    tier_info = TIERS[req.tier]
    
    try:
        suby = SubyClient()
        checkout_url = await suby.create_checkout(
            user_id=user.user_id,
            workspace_id=user.workspace_id,
            tier_id=req.tier,
            amount_usd=tier_info["price_usd"]
        )
        return {"checkoutUrl": checkout_url}
    except Exception as e:
        logger.exception("Suby checkout failed")
        raise HTTPException(status_code=500, detail="Payment gateway error")

from fastapi.responses import RedirectResponse
import uuid

@router.get("/mock-success")
async def mock_checkout_success(user_id: str, workspace_id: str, tier_id: str):
    """Simulate a successful payment for local testing when real Suby keys are not present."""
    if tier_id in TIERS:
        minutes = TIERS[tier_id]["minutes"]
        price = TIERS[tier_id]["price_usd"]
        transaction_id = f"tx_{uuid.uuid4().hex[:8]}"
        
        from app.core import db as database
        from app.core.db import _get_service_role_client
        client = _get_service_role_client()
        
        await database.add_transaction(
            client,
            transaction_id=transaction_id,
            workspace_id=workspace_id,
            tier=tier_id,
            amount_usd=price,
            minutes_added=minutes
        )
        await database.add_workspace_minutes(client, workspace_id=workspace_id, minutes=minutes)
        logger.info(f"[MOCK_PAYMENT] Added {minutes} minutes to workspace {safe_ws(workspace_id)}")
        
    return RedirectResponse(url="/tts/billing?payment=success")

@router.post("/test-webhook")
async def test_suby_webhook(request: Request):
    """Local testing endpoint for webhooks (bypasses signature check for local testing)."""
    try:
        event = await request.json()
        data = event.get("data", event)
        user_id = data.get("user_id", "test_user")
        workspace_id = data.get("workspace_id")
        tier_id = data.get("tier_id", "pro")
        transaction_id = data.get("transaction_id", f"tx_test_{uuid.uuid4().hex[:8]}")
        
        if not workspace_id:
            raise HTTPException(status_code=400, detail="Missing workspace_id")
            
        if tier_id in TIERS:
            minutes = TIERS[tier_id]["minutes"]
            price = TIERS[tier_id]["price_usd"]
            
            from app.core import db as database
            from app.core.db import _get_service_role_client
            client = _get_service_role_client()
            
            await database.add_transaction(
                client,
                transaction_id=transaction_id,
                workspace_id=workspace_id,
                tier=tier_id,
                amount_usd=price,
                minutes_added=minutes
            )
            new_balance = await database.add_workspace_minutes(client, workspace_id, minutes)
            logger.info(f"[TEST_WEBHOOK] Added {minutes} minutes to workspace {safe_ws(workspace_id)}. New balance: {new_balance}")
            return {"status": "ok", "message": f"Successfully added {minutes} minutes to workspace {workspace_id}", "new_balance": new_balance}
        else:
            raise HTTPException(status_code=400, detail="Invalid tier_id")
    except Exception as e:
        logger.exception("Test webhook failed")
        raise HTTPException(status_code=400, detail=str(e))

from fastapi import BackgroundTasks

async def _process_webhook_event(event: Dict[str, Any]):
    """Asynchronous background worker to process webhook payload without blocking HTTP response."""
    try:
        event_type = str(event.get("type", "")).upper()
        event_data = event.get("data", {})
        
        if event_type in ("PAYMENT_SUCCESS", "PAYMENT.SUCCESS"):
            payment = event_data.get("payment", {}) if "payment" in event_data else event_data
            context = event_data.get("context", {})
            metadata = context.get("metadata", {}) if isinstance(context, dict) else {}
            
            user_id = event_data.get("user_id") or metadata.get("user_id") or payment.get("customerEmail") or "unknown"
            workspace_id = event_data.get("workspace_id") or metadata.get("workspace_id") or context.get("externalRef")
            tier_id = event_data.get("tier_id") or metadata.get("tier_id") or "pro"
            transaction_id = event_data.get("transaction_id") or payment.get("id") or f"tx_{uuid.uuid4().hex[:8]}"
            
            if not workspace_id:
                logger.error("[WEBHOOK] Async processing error: missing workspace_id")
                return
                
            if tier_id in TIERS:
                minutes = TIERS[tier_id]["minutes"]
                price = TIERS[tier_id]["price_usd"]
                
                from app.core import db as database
                from app.core.db import _get_service_role_client
                client = _get_service_role_client()
                
                # Atomic deduplication and minute increment
                res = await database.process_payment_success_atomic(
                    client,
                    transaction_id=transaction_id,
                    workspace_id=workspace_id,
                    tier=tier_id,
                    amount_usd=price,
                    minutes_added=minutes
                )
                logger.info(f"[WEBHOOK_ASYNC] Atomic processing result for {transaction_id}: {res}")
                
        elif event_type in ("PAYMENT_REFUNDED", "PAYMENT.REFUNDED"):
            workspace_id = event_data.get("workspace_id") or event_data.get("context", {}).get("metadata", {}).get("workspace_id")
            tier_id = event_data.get("tier_id") or event_data.get("context", {}).get("metadata", {}).get("tier_id", "pro")
            if workspace_id and tier_id in TIERS:
                minutes = TIERS[tier_id]["minutes"]
                from app.core import db as database
                from app.core.db import _get_service_role_client
                client = _get_service_role_client()
                result = await database.handle_refund_kill_switch(client, workspace_id=workspace_id, amount_deducted=minutes)
                logger.warning(f"[WEBHOOK_KILL_SWITCH] Refund active kill-switch executed for {safe_ws(workspace_id)}: {result}")
                
        elif event_type in ("PAYMENT_FAILED", "PAYMENT.FAILED"):
            logger.warning(f"[WEBHOOK_ASYNC] Payment failed event logged: {event_data.get('id', 'unknown')}")
    except Exception as e:
        logger.exception("[WEBHOOK_ASYNC] Processing background task error: %s", e)

@router.post("/webhook")
async def suby_webhook(request: Request, background_tasks: BackgroundTasks):
    """Receive payment webhook from Suby. Verifies signature synchronously, then queues event handling."""
    payload = await request.body()
    signature = request.headers.get("x-suby-signature")
    
    suby = SubyClient()
    if not suby.verify_signature(payload, signature):
        logger.warning("Invalid Suby webhook signature")
        raise HTTPException(status_code=401, detail="Invalid signature")
        
    try:
        event = await request.json()
        background_tasks.add_task(_process_webhook_event, event)
        return {"status": "accepted"}
    except Exception as e:
        logger.exception("Webhook payload parsing failed")
        raise HTTPException(status_code=400, detail="Invalid webhook payload")
