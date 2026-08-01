import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.services.vcta.isolation import load_and_validate, _verify_sha256, MAX_AUDIO_DURATION_SEC
from app.services.vcta.translator import _sanitize_entity, _get_http_client

def test_load_and_validate_duration_limit(tmp_path):
    fake_wav = tmp_path / "test.wav"
    fake_wav.write_bytes(b"RIFF....WAVEfmt ....data....")

    mock_info = MagicMock()
    mock_info.duration = MAX_AUDIO_DURATION_SEC + 100 # Exceed limit

    with patch("soundfile.info", return_value=mock_info):
        with pytest.raises(ValueError, match="exceeds the maximum limit"):
            load_and_validate(str(fake_wav))

def test_verify_sha256_prod_fail_closed(tmp_path):
    dummy_file = tmp_path / "model.ckpt"
    dummy_file.write_text("dummy model content")

    with patch.dict(os.environ, {"PIRD_ENV": "prod"}):
        with pytest.raises(RuntimeError, match="Security Violation: Unpinned model checkpoint"):
            _verify_sha256(dummy_file, "TODO_PIN_SHA256")

def test_sanitize_entity():
    raw_entity = "Brand Name <script>alert(1)</script> Drop Table"
    sanitized = _sanitize_entity(raw_entity)
    assert "<" not in sanitized
    assert ">" not in sanitized
    assert "(" not in sanitized
    assert ")" not in sanitized
    assert len(sanitized) <= 64

def test_http_client_pooling():
    client1 = _get_http_client()
    client2 = _get_http_client()
    assert client1 is client2
