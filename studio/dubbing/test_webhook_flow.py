import os
import hmac
import hashlib
import json
import base64
import httpx
import uuid
import asyncio

# --- CONFIGURATION ---
# Change these to match your local setup or remote server
WEBHOOK_URL = "http://localhost:8002/api/payments/webhook"
# Automatically load the secret from the local .env file so it always matches the local server
from dotenv import load_dotenv
load_dotenv()
WEBHOOK_SECRET = os.getenv("SUBY_WEBHOOK_SECRET", "sandbox_secret")

async def test_webhook():
    print(f"Testing webhook endpoint at: {WEBHOOK_URL}")
    
    # 1. Construct the Composite Tracking ID exactly how the frontend/backend does
    composite_data = {
        "user_id": "user_3HMmodZFCj6xyDugq8c9spyvbmX",
        "workspace_id": "live-test-org",
        "tier_id": "starter" # Must match one of your tiers: starter, pro, creator
    }
    
    json_str = json.dumps(composite_data)
    encoded_b64 = base64.urlsafe_b64encode(json_str.encode('utf-8')).decode('utf-8')
    print(f"\n[1] Generated clientReferenceId: {encoded_b64}")
    
    # 2. Construct the Payload
    payload_dict = {
        "id": f"evt_{uuid.uuid4().hex[:12]}",
        "type": "checkout.success",
        "data": {
            "clientReferenceId": encoded_b64,
            "amountCents": 1000,
            "currency": "USD",
            "status": "COMPLETED"
        }
    }
    
    # Suby's payload is stringified JSON
    # Note: separators=(',', ':') ensures no extra spaces are added, which is critical for HMAC matching
    payload_bytes = json.dumps(payload_dict, separators=(',', ':')).encode('utf-8')
    print(f"\n[2] Constructed Payload: {payload_dict}")
    
    # 3. Generate HMAC SHA256 Signature
    signature = hmac.new(
        WEBHOOK_SECRET.encode('utf-8'),
        payload_bytes,
        hashlib.sha256
    ).hexdigest()
    print(f"\n[3] Generated Signature: {signature}")
    
    # 4. Send the Request
    headers = {
        "Content-Type": "application/json",
        "x-suby-signature": signature,
        "x-webhook-event": "checkout.success"
    }
    
    print("\n[4] Sending POST request...")
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(WEBHOOK_URL, content=payload_bytes, headers=headers)
            
            print(f"\n[5] Response Status: {response.status_code}")
            try:
                print(f"[5] Response Body: {json.dumps(response.json(), indent=2)}")
            except:
                print(f"[5] Response Body (Raw): {response.text}")
                
            if response.is_success:
                print("\n[SUCCESS] Webhook test passed! The server successfully verified the signature, decoded the base64, and fired the atomic mutation.")
            else:
                print("\n[FAILED] Webhook test failed. Check the FastAPI logs to see why it rejected the payload.")
                
        except Exception as e:
            print(f"\n[ERROR] Request failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_webhook())
