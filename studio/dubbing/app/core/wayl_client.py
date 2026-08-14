import os
import hmac
import hashlib
import logging
from typing import Dict, Any, Optional
import httpx

logger = logging.getLogger(__name__)

class WaylClient:
    def __init__(self):
        self.api_token = (os.getenv("WAYL_API_TOKEN", "") or "").strip().strip('"').strip("'")
        self.webhook_secret = (os.getenv("WAYL_WEBHOOK_SECRET", "") or "").strip().strip('"').strip("'")

    def _get_env(self) -> str:
        wayl_env_override = (os.getenv("WAYL_ENV", "") or "").strip().lower()
        pird_env = (os.getenv("PIRD_ENV", "dev") or "").strip().lower()
        if wayl_env_override in ("live", "test"):
            return wayl_env_override
        return "live" if pird_env in ("prod", "production") else "test"

    def _get_base_url(self) -> str:
        # Default to production server (https://api.thewayl.com) where registered merchant API keys exist.
        # It handles both "env": "live" and "env": "test" payloads seamlessly.
        return (os.getenv("WAYL_BASE_URL", "https://api.thewayl.com") or "https://api.thewayl.com").strip().rstrip("/")

    async def verify_auth_key(self) -> Dict[str, Any]:
        """Execute a test call to GET /api/v1/verify-auth-key using WAYL_API_TOKEN."""
        headers = {
            "X-WAYL-AUTHENTICATION": self.api_token,
            "Content-Type": "application/json"
        }
        url = f"{self._get_base_url()}/api/v1/verify-auth-key"
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.get(url, headers=headers)
            if res.status_code != 200:
                logger.error(f"[WAYL] Key verification failed: {res.status_code} - {res.text}")
                res.raise_for_status()
            return res.json()

    async def create_payment_link(
        self,
        reference_id: str,
        amount_iqd: int,
        redirection_url: str,
        webhook_url: Optional[str] = None
    ) -> str:
        """Make a POST request to /api/v1/links to create a payment link.
        
        Headers: "X-WAYL-AUTHENTICATION": os.getenv("WAYL_API_TOKEN")
        Payload: env, referenceId, total (integer in IQD), currency ("IQD"), lineItem, webhookUrl, webhookSecret, redirectionUrl
        """
        if not self.api_token:
            logger.error("[WAYL] WAYL_API_TOKEN is missing in environment variables")
            raise ValueError("WAYL_API_TOKEN environment variable is not configured on the server")

        if not webhook_url:
            base_webhook = os.getenv("DUBBING_URL", "https://api.doblaj.com")
            webhook_url = f"{base_webhook.rstrip('/')}/api/payments/webhook"

        wayl_env = self._get_env()
        target_api_url = f"{self._get_base_url()}/api/v1/links"

        # Wayl requires minimum 1000 IQD
        final_amount = max(1000, int(amount_iqd))

        payload = {
            "env": wayl_env,
            "referenceId": reference_id,
            "total": final_amount,
            "currency": "IQD",  # Strictly hardcoded as IQD
            "lineItem": [
                {
                    "label": f"Doblaj Credits Package ({final_amount} IQD)",
                    "amount": final_amount,
                    "type": "increase"
                }
            ],
            "webhookUrl": webhook_url,
            "webhookSecret": self.webhook_secret,
            "redirectionUrl": redirection_url,
        }

        headers = {
            "X-WAYL-AUTHENTICATION": self.api_token,
            "Content-Type": "application/json"
        }

        logger.info(f"[WAYL] Creating payment link on {target_api_url} with env={wayl_env} for referenceId={reference_id}, total={final_amount} IQD")

        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post(target_api_url, json=payload, headers=headers)
            if res.status_code not in (200, 201):
                logger.error(f"[WAYL] Payment link creation failed: {res.status_code} - {res.text}")
                res.raise_for_status()
            
            data = res.json()
            if isinstance(data, dict) and "data" in data and isinstance(data["data"], dict) and "url" in data["data"]:
                return data["data"]["url"]
            elif isinstance(data, dict) and "url" in data:
                return data["url"]
            else:
                logger.error(f"[WAYL] Unexpected response structure: {data}")
                raise ValueError("Invalid response structure from Wayl API")

    def verify_webhook_signature(self, raw_body_bytes: bytes, signature_header: Optional[str]) -> bool:
        """Computes HMAC-SHA256 signature using WAYL_WEBHOOK_SECRET over raw request bytes.
        Compares hash to x-wayl-signature-256 header.
        """
        if not signature_header or not self.webhook_secret:
            logger.warning("[WAYL] Missing signature header or webhook secret")
            return False

        try:
            expected_mac = hmac.new(
                self.webhook_secret.encode('utf-8'),
                raw_body_bytes,
                hashlib.sha256
            ).hexdigest()
            return hmac.compare_digest(expected_mac.lower(), signature_header.strip().lower())
        except Exception as e:
            logger.error(f"[WAYL] Signature verification error: {e}")
            return False

    async def create_refund(
        self,
        reference_id: str,
        amount_iqd: int,
        reason: str
    ) -> Dict[str, Any]:
        """Request a refund for a completed payment via Wayl API POST /api/v1/refunds.
        
        Requirements per Wayl Spec:
        - referenceId: Order reference ID (e.g. ref_xxx)
        - amount: IQD amount (minimum 1000)
        - reason: Minimum 100 characters string
        """
        if not self.api_token:
            raise ValueError("WAYL_API_TOKEN environment variable is not configured on the server")

        clean_reason = reason.strip()
        if len(clean_reason) < 100:
            clean_reason = (clean_reason + " — Customer refund processed via Doblaj platform administration portal.").ljust(100, ".")

        final_amount = max(1000, int(amount_iqd))
        target_url = f"{self._get_base_url()}/api/v1/refunds"

        payload = {
            "referenceId": reference_id,
            "amount": final_amount,
            "reason": clean_reason[:1500],
        }

        headers = {
            "X-WAYL-AUTHENTICATION": self.api_token,
            "Content-Type": "application/json"
        }

        logger.info(f"[WAYL] Initiating refund for referenceId={reference_id}, amount={final_amount} IQD")

        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post(target_url, json=payload, headers=headers)
            if res.status_code not in (200, 201):
                logger.error(f"[WAYL] Refund creation failed: {res.status_code} - {res.text}")
                res.raise_for_status()
            return res.json()
