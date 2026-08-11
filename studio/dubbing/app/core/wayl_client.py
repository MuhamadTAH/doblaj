import os
import hmac
import hashlib
import logging
from typing import Dict, Any, Optional
import httpx

logger = logging.getLogger(__name__)

class WaylClient:
    def __init__(self):
        self.api_token = os.getenv("WAYL_API_TOKEN", "")
        self.webhook_secret = os.getenv("WAYL_WEBHOOK_SECRET", "")
        self.api_url = "https://api.thewayl.com/api/v1/links"
        self.verify_url = "https://api.thewayl.com/api/v1/verify-auth-key"

    async def verify_auth_key(self) -> Dict[str, Any]:
        """Execute a test call to GET /api/v1/verify-auth-key using WAYL_API_TOKEN."""
        headers = {
            "X-WAYL-AUTHENTICATION": self.api_token,
            "Content-Type": "application/json"
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.get(self.verify_url, headers=headers)
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
        """Make a POST request to https://api.thewayl.com/api/v1/links to create a payment link.
        
        Headers: "X-WAYL-AUTHENTICATION": os.getenv("WAYL_API_TOKEN")
        Payload: env, referenceId, total (integer in IQD), currency ("IQD"), webhookUrl, webhookSecret, redirectionUrl
        """
        if not webhook_url:
            base_webhook = os.getenv("DUBBING_URL", "http://localhost:8002")
            webhook_url = f"{base_webhook.rstrip('/')}/api/payments/webhook"

        payload = {
            "env": os.getenv("PIRD_ENV", "dev"),
            "referenceId": reference_id,
            "total": int(amount_iqd),
            "currency": "IQD",  # Strictly hardcoded as IQD
            "webhookUrl": webhook_url,
            "webhookSecret": self.webhook_secret,
            "redirectionUrl": redirection_url,
        }

        headers = {
            "X-WAYL-AUTHENTICATION": self.api_token,
            "Content-Type": "application/json"
        }

        logger.info(f"[WAYL] Creating payment link for referenceId={reference_id}, total={amount_iqd} IQD")

        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post(self.api_url, json=payload, headers=headers)
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
