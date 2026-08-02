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

@router.options("/checkout")
@router.options("/checkout/")
async def options_checkout_session():
    return {}

@router.post("/checkout")
@router.post("/checkout/")
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
        
    return RedirectResponse(url="/billing?payment=success")

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
    """Receive payment webhook from Suby. Verifies signature & persists directly to Convex DB before returning 200 OK."""
    payload = await request.body()
    signature = request.headers.get("x-suby-signature") or request.headers.get("x-webhook-signature")
    
    suby = SubyClient()
    if not suby.verify_signature(payload, signature):
        logger.warning("Invalid Suby webhook signature")
        raise HTTPException(status_code=401, detail="Invalid signature")
        
    try:
        event = await request.json()
        event_id = event.get("id") or f"evt_{uuid.uuid4().hex[:12]}"
        event_type = event.get("type") or request.headers.get("x-webhook-event", "PAYMENT_SUCCESS")
        
        from app.core import db as database
        from app.core.db import _get_service_role_client
        client = _get_service_role_client()
        
        # DURABLE INGESTION: Writes raw webhook to webhookEvents table in Convex before returning 200 OK
        res = await database.record_and_process_webhook_durable(
            client,
            event_id=event_id,
            event_type=event_type,
            payload=event
        )
        logger.info(f"[DURABLE_WEBHOOK] Persisted and processed event {event_id}: {res}")
        return {"status": "ok", "persisted": True, "result": res}
    except Exception as e:
        logger.exception("Webhook durable processing failed")
        raise HTTPException(status_code=400, detail=f"Webhook error: {str(e)}")
