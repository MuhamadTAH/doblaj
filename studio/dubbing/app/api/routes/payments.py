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

@router.post("/webhook")
async def suby_webhook(request: Request):
    """Receive payment success from Suby."""
    payload = await request.body()
    signature = request.headers.get("x-suby-signature")
    
    suby = SubyClient()
    if not suby.verify_signature(payload, signature):
        logger.warning("Invalid Suby webhook signature")
        raise HTTPException(status_code=401, detail="Invalid signature")
        
    try:
        event = await request.json()
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
                logger.error("[WEBHOOK] Payload missing workspace_id")
                raise HTTPException(status_code=400, detail="Missing workspace_id")
                
            if tier_id in TIERS:
                minutes = TIERS[tier_id]["minutes"]
                price = TIERS[tier_id]["price_usd"]
                
                from app.core import db as database
                from app.core.db import _get_service_role_client
                client = _get_service_role_client()
                
                if await database.transaction_exists(client, transaction_id):
                    logger.info(f"[WEBHOOK] Transaction {transaction_id} already processed. Skipping.")
                    return {"status": "ok", "message": "Already processed"}
                
                await database.add_transaction(
                    client,
                    transaction_id=transaction_id,
                    workspace_id=workspace_id,
                    tier=tier_id,
                    amount_usd=price,
                    minutes_added=minutes
                )
                new_balance = await database.add_workspace_minutes(client, workspace_id, minutes)
                logger.info(f"[WEBHOOK] Added {minutes} mins to workspace {safe_ws(workspace_id)}. New balance: {new_balance}")
                
        elif event_type in ("PAYMENT_REFUNDED", "PAYMENT.REFUNDED"):
            workspace_id = event_data.get("workspace_id") or event_data.get("context", {}).get("metadata", {}).get("workspace_id")
            tier_id = event_data.get("tier_id") or event_data.get("context", {}).get("metadata", {}).get("tier_id", "pro")
            if workspace_id and tier_id in TIERS:
                minutes = TIERS[tier_id]["minutes"]
                from app.core import db as database
                from app.core.db import _get_service_role_client
                client = _get_service_role_client()
                await database.deduct_workspace_minutes(client, workspace_id=workspace_id, minutes=minutes)
                logger.warning(f"[WEBHOOK] Refund processed: Deducted {minutes} mins from workspace {safe_ws(workspace_id)}")
                
        elif event_type in ("PAYMENT_FAILED", "PAYMENT.FAILED"):
            logger.warning(f"[WEBHOOK] Payment failed event received: {event_data.get('id', 'unknown')}")
            
        return {"status": "ok"}
    except Exception as e:
        logger.exception("Webhook processing failed")
        raise HTTPException(status_code=400, detail="Webhook error")
