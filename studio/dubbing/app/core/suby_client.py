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
