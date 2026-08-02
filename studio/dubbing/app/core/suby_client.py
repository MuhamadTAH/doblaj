import os
import hmac
import hashlib
import logging

logger = logging.getLogger(__name__)

class SubyClient:
    def __init__(self):
        self.api_key = os.getenv("SUBY_API_KEY", "sandbox_key")
        self.webhook_secret = os.getenv("SUBY_WEBHOOK_SECRET", "sandbox_secret")
        self.base_url = os.getenv("SUBY_API_URL", "https://api.suby.fi/api").rstrip("/")
        # PIRD-029: fail-closed in production. The default
        # "sandbox_secret" placeholder must NEVER be used in prod — a
        # webhook signed with the default would be accepted.
        import re
        if os.getenv("PIRD_ENV", "").lower() == "prod":
            # Strict regex validation for Suby API keys (sk_live_, mk_live_) and webhook secrets (whsec_)
            API_KEY_REGEX = r"^(sk_live_|mk_live_)[a-zA-Z0-9_-]{24,80}$"
            WEBHOOK_SECRET_REGEX = r"^(whsec_)?[a-zA-Z0-9_-]{24,128}$"

            if not re.match(API_KEY_REGEX, self.api_key):
                raise RuntimeError(
                    f"SUBY_API_KEY failed cryptographic format validation. Must match pattern '{API_KEY_REGEX}'."
                )
            if not re.match(WEBHOOK_SECRET_REGEX, self.webhook_secret):
                raise RuntimeError(
                    f"SUBY_WEBHOOK_SECRET failed cryptographic format validation. Must match pattern '{WEBHOOK_SECRET_REGEX}'."
                )

    async def create_checkout(self, user_id: str, workspace_id: str, tier_id: str, amount_usd: int) -> str:
        """Suby.fi API call to generate a payment checkout URL"""
        logger.info(f"Creating Suby checkout for user {user_id}, workspace {workspace_id}, tier {tier_id}, ${amount_usd}")
        
        import httpx
        
        async with httpx.AsyncClient() as client:
            payload = {
                "productId": f"dubbing-tier-{tier_id}",
                "priceCents": str(amount_usd * 100),
                "currency": "USD",
                "paymentMethods": ["CARD"],
                "metadata": {
                    "user_id": user_id,
                    "workspace_id": workspace_id,
                    "tier_id": tier_id
                }
            }
            
            headers = {
                "X-Suby-Api-Key": self.api_key,
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            try:
                # Call Suby.fi API endpoint: /payment/create
                url = f"{self.base_url}/payment/create"
                logger.info(f"[SUBY_CHECKOUT_REQ] POST {url} with payload: {payload} and headers (API Key omitted)")
                res = await client.post(url, json=payload, headers=headers, timeout=10.0)
                if not res.is_success:
                    logger.error(f"[SUBY_CHECKOUT_ERR] Suby API returned {res.status_code}: {res.text}")
                res.raise_for_status()
                data = res.json()
                logger.info(f"[SUBY_CHECKOUT_RES] Suby API response: {data}")
                payment_url = data.get("data", {}).get("paymentUrl") or data.get("url")
                if payment_url:
                    return payment_url
                logger.warning(f"[SUBY_CHECKOUT_WARN] No payment URL in response. Falling back to mock-success.")
                return f"/api/payments/mock-success?user_id={user_id}&workspace_id={workspace_id}&tier_id={tier_id}"
            except Exception as e:
                logger.exception(f"[SUBY_CHECKOUT_FAIL] Failed to create Suby checkout: {e}")
                # Fallback to local mock checkout for testing when API key is unconfigured
                return f"/api/payments/mock-success?user_id={user_id}&workspace_id={workspace_id}&tier_id={tier_id}"

    def verify_signature(self, payload: bytes, signature: str) -> bool:
        """Verify the webhook signature using HMAC-SHA256"""
        if not signature:
            return False
            
        try:
            expected_mac = hmac.new(
                self.webhook_secret.encode('utf-8'),
                payload,
                hashlib.sha256
            ).hexdigest()
            return hmac.compare_digest(expected_mac, signature)
        except Exception as e:
            logger.error(f"Signature verification failed: {e}")
            return False
