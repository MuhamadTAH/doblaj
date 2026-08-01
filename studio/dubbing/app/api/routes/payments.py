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
        if event.get("type") == "payment.success":
            user_id = event["data"]["user_id"]
            workspace_id = event["data"].get("workspace_id")
            tier_id = event["data"]["tier_id"]
            transaction_id = event["data"]["transaction_id"]
            
            if not workspace_id:
                logger.error("Webhook payload missing workspace_id")
                raise HTTPException(status_code=400, detail="Missing workspace_id")
                
            if tier_id in TIERS:
                minutes = TIERS[tier_id]["minutes"]
                price = TIERS[tier_id]["price_usd"]
                logger.info(f"Adding {minutes} minutes to workspace {safe_ws(workspace_id)} (user {user_id})")
                
                from app.core import db as database
                from app.core.db import _get_service_role_client
                
                client = _get_service_role_client()
                
                # Check if transaction was already processed
                if await database.transaction_exists(client, transaction_id):
                    logger.info(f"Transaction {transaction_id} already processed. Skipping.")
                    return {"status": "ok", "message": "Already processed"}
                
                # 1. Log transaction
                await database.add_transaction(
                    client,
                    transaction_id=transaction_id,
                    workspace_id=workspace_id,
                    tier=tier_id,
                    amount_usd=price,
                    minutes_added=minutes
                )
                
                # 2. Add minutes to workspace
                new_balance = await database.add_workspace_minutes(client, workspace_id, minutes)
                logger.info(f"Workspace {safe_ws(workspace_id)} balance updated. New balance: {new_balance} minutes.")
                
        return {"status": "ok"}
    except Exception as e:
        logger.exception("Webhook processing failed")
        raise HTTPException(status_code=400, detail="Webhook error")
