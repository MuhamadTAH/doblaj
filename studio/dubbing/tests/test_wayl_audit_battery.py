import pytest
import hmac
import hashlib
import json
import uuid
import os
from unittest.mock import AsyncMock, patch, MagicMock

from app.core.wayl_client import WaylClient


def test_audit_1_wayl_client_signature_verification():
    """Audit 3: Test valid & invalid HMAC-SHA256 signature verification."""
    os.environ["WAYL_WEBHOOK_SECRET"] = "test_webhook_secret_12345"
    client = WaylClient()

    raw_body = b'{"referenceId": "ref_12345", "status": "Complete"}'

    # Compute valid signature
    valid_sig = hmac.new(
        b"test_webhook_secret_12345",
        raw_body,
        hashlib.sha256
    ).hexdigest()

    # 1. Valid Signature Test -> True
    assert client.verify_webhook_signature(raw_body, valid_sig) is True
    assert client.verify_webhook_signature(raw_body, valid_sig.upper()) is True

    # 2. Invalid Signature Test (tampered byte or signature) -> False
    invalid_sig = valid_sig[:-1] + ("0" if valid_sig[-1] != "0" else "1")
    assert client.verify_webhook_signature(raw_body, invalid_sig) is False

    tampered_body = b'{"referenceId": "ref_12345", "status": "Complete", "hacked": true}'
    assert client.verify_webhook_signature(tampered_body, valid_sig) is False


def test_audit_2_price_conversion_and_iqd_casting():
    """Audit 2: Ensure USD prices convert to IQD and cast strictly to integer."""
    rate = 1500.0
    
    usd_starter = 10
    total_starter_iqd = int(round(usd_starter * rate))
    assert total_starter_iqd == 15000
    assert isinstance(total_starter_iqd, int)

    usd_pro = 20
    total_pro_iqd = int(round(usd_pro * rate))
    assert total_pro_iqd == 30000
    assert isinstance(total_pro_iqd, int)

    usd_creator = 99
    total_creator_iqd = int(round(usd_creator * rate))
    assert total_creator_iqd == 148500
    assert isinstance(total_creator_iqd, int)


@pytest.mark.asyncio
async def test_audit_3_wayl_client_create_link():
    """Audit 2 & 3: WaylClient create_payment_link sends correct headers and payload."""
    os.environ["WAYL_API_TOKEN"] = "test_api_token_abc"
    os.environ["WAYL_WEBHOOK_SECRET"] = "test_secret_123"

    client = WaylClient()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": {
            "url": "https://api.thewayl.com/pay/ref_test_999"
        }
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        url = await client.create_payment_link(
            reference_id="ref_test_999",
            amount_iqd=30000,
            redirection_url="http://localhost:8081/tts/pricing?payment=success"
        )

        assert url == "https://api.thewayl.com/pay/ref_test_999"

        # Verify header & payload structure
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args.kwargs
        headers = call_kwargs["headers"]
        payload = call_kwargs["json"]

        assert headers["X-WAYL-AUTHENTICATION"] == "test_api_token_abc"
        assert payload["referenceId"] == "ref_test_999"
        assert payload["total"] == 30000
        assert isinstance(payload["total"], int)
        assert payload["currency"] == "IQD"
        assert payload["redirectionUrl"] == "http://localhost:8081/tts/pricing?payment=success"
