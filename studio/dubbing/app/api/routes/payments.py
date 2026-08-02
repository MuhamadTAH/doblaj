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
        import os
        import json
        import base64
        import urllib.parse
        
        tier_link = os.getenv(f"SUBY_LINK_{req.tier.upper()}")
        if not tier_link:
            raise HTTPException(status_code=400, detail=f"No static checkout link available for tier {req.tier}")

        # Build Composite Tracking ID
        composite_data = {
            "user_id": user.user_id,
            "workspace_id": user.workspace_id,
            "tier_id": req.tier
        }
        
        # Safely URL-safe Base64 encode the JSON
        json_str = json.dumps(composite_data)
        encoded_b64 = base64.urlsafe_b64encode(json_str.encode('utf-8')).decode('utf-8')
        
        # The encode doesn't need quote if it's urlsafe, but it's fine
        checkout_url = f"{tier_link}?clientReferenceId={encoded_b64}"
        
        return {"checkoutUrl": checkout_url}
    except Exception as e:
        logger.exception("Checkout URL generation failed")
        raise HTTPException(status_code=500, detail=str(e))

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
            new_balance = await database.add_workspace_minutes(client, workspace_id=workspace_id, minutes=minutes)
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
        import base64
        import json
        
        event = await request.json()
        event_id = event.get("id") or f"evt_{uuid.uuid4().hex[:12]}"
        event_type = event.get("type") or request.headers.get("x-webhook-event", "PAYMENT_SUCCESS")
        
        # Strict Event Validation
        if event_type not in ("checkout.success", "payment.success", "PAYMENT_SUCCESS"):
            logger.info(f"Ignoring non-success event type: {event_type}")
            return {"status": "ignored", "reason": "not a success event"}
        
        data = event.get("data", event)
        client_ref = data.get("clientReferenceId")
        if not client_ref:
            raise HTTPException(status_code=400, detail="Missing clientReferenceId")
            
        try:
            # Base64-decode the JSON
            decoded_bytes = base64.urlsafe_b64decode(client_ref.encode('utf-8'))
            composite_data = json.loads(decoded_bytes.decode('utf-8'))
        except Exception as parse_e:
            logger.error(f"Failed to parse clientReferenceId: {parse_e}")
            raise HTTPException(status_code=400, detail="Invalid clientReferenceId format")
            
        workspace_id = composite_data.get("workspace_id")
        tier_id = composite_data.get("tier_id")
        user_id = composite_data.get("user_id")
        transaction_id = event_id # Use event ID or transaction ID for idempotency
        
        if not workspace_id or not tier_id:
             raise HTTPException(status_code=400, detail="Missing required IDs in payload")
             
        tier_info = TIERS.get(tier_id)
        if not tier_info:
            raise HTTPException(status_code=400, detail="Invalid tier_id in payload")
            
        minutes_added = tier_info["minutes"]
        amount_usd = tier_info["price_usd"]
        
        from app.core import db as database
        from app.core.db import _get_service_role_client
        client = _get_service_role_client()
        
        # Atomic Idempotency & Credit
        # Calls the Convex transaction that checks if event exists, and if not, adds minutes.
        res = await database.process_payment_success_atomic(
            client,
            transaction_id=transaction_id,
            workspace_id=workspace_id,
            tier=tier_id,
            amount_usd=amount_usd,
            minutes_added=minutes_added
        )
        
        logger.info(f"[ATOMIC_WEBHOOK] Processed event {event_id}: {res}")
        return {"status": "ok", "persisted": True, "result": res}
    except Exception as e:
        logger.exception("Webhook atomic processing failed")
        raise HTTPException(status_code=400, detail=f"Webhook error: {str(e)}")
