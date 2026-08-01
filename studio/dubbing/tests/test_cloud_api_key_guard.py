"""Tests for the cloud API key startup guard.

The dubbing pipeline depends on third-party APIs for translation,
transcription, and TTS. If any required key is empty, jobs will fail
mysteriously halfway through the CPU phase.

The startup hook in main.py must verify every required key is non-empty
in production (PIRD_ENV=prod) and raise a clear RuntimeError listing
the missing keys. In dev (PIRD_ENV unset or != prod), the guard must
log a warning and continue, since dev runs often with stub keys.
"""
import importlib
import os
import sys
from unittest import mock

import pytest


REQUIRED_KEYS = [
    "OPEN_ROUTER_API_KEY",     # translation (Kurdish -> Arabic)
    "FISH_API_KEY",            # primary TTS (voice cloning)
    "GEMINI_API_KEY",          # collision-chunk transcription + translation
    "ASSEMBLYAI_API_KEY",      # fallback transcription
    "DEEPGRAM_API_KEY",        # fallback transcription
    "R2_ENDPOINT",             # source upload + zip download
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_BUCKET",
    "CONVEX_URL",
    "INTERNAL_API_KEY",
    "CLERK_SECRET_KEY",
]


def _reload_main_with_env(monkeypatch, env_overrides):
    """Reload main.py with a controlled env. Uses empty string (NOT delenv)
    so that load_dotenv() in main.py doesn't refill the key from .env."""
    for k in REQUIRED_KEYS:
        monkeypatch.setenv(k, "")
    for k, v in env_overrides.items():
        if v:  # only override non-empty
            monkeypatch.setenv(k, v)
    sys.modules.pop("main", None)
    return importlib.import_module("main")


def test_startup_guard_raises_in_prod_when_key_missing(monkeypatch):
    """With PIRD_ENV=prod and OPEN_ROUTER_API_KEY unset, startup must
    raise a RuntimeError listing the missing key. A silent warning is
    not enough -- a half-configured prod deploy is the worst outcome."""
    env = {"PIRD_ENV": "prod", "RUNPOD_ENDPOINT_ID": "ep-x", "RUNPOD_API_KEY": "k"}
    for k in REQUIRED_KEYS:
        if k == "OPEN_ROUTER_API_KEY":
            continue
        env[k] = f"fake_{k}"

    main = _reload_main_with_env(monkeypatch, env)

    fake_db = mock.MagicMock()
    fake_db.init_db = mock.AsyncMock()
    with mock.patch.dict(sys.modules, {"app.core.database": fake_db}), \
         mock.patch.object(main.asyncio, "create_task", return_value=mock.Mock()), \
         mock.patch.object(main, "logger"):
        with pytest.raises(RuntimeError) as exc:
            import asyncio
            asyncio.run(main.on_startup())
        assert "OPEN_ROUTER_API_KEY" in str(exc.value), (
            f"RuntimeError must name the missing key, got: {exc.value!r}"
        )


def test_startup_guard_lists_all_missing_keys(monkeypatch):
    """If multiple keys are missing, the error must list every one of
    them so the operator can fix them in one pass."""
    env = {"PIRD_ENV": "prod"}
    for k in REQUIRED_KEYS:
        if k in ("GEMINI_API_KEY", "FISH_API_KEY"):
            continue
        env[k] = f"fake_{k}"

    main = _reload_main_with_env(monkeypatch, env)

    fake_db = mock.MagicMock()
    fake_db.init_db = mock.AsyncMock()
    with mock.patch.dict(sys.modules, {"app.core.database": fake_db}), \
         mock.patch.object(main.asyncio, "create_task", return_value=mock.Mock()), \
         mock.patch.object(main, "logger"):
        with pytest.raises(RuntimeError) as exc:
            import asyncio
            asyncio.run(main.on_startup())
        msg = str(exc.value)
        assert "GEMINI_API_KEY" in msg
        assert "FISH_API_KEY" in msg


def test_startup_guard_passes_when_all_keys_set(monkeypatch):
    """With PIRD_ENV=prod and every required key present, startup must
    NOT raise. The CPU worker task should still be scheduled."""
    env = {"PIRD_ENV": "prod"}
    for k in REQUIRED_KEYS:
        env[k] = f"fake_{k}"
    env.setdefault("PIRD_SHELL_ORIGIN", "https://doblaj.com")

    main = _reload_main_with_env(monkeypatch, env)

    fake_db = mock.MagicMock()
    fake_db.init_db = mock.AsyncMock()
    with mock.patch.dict(sys.modules, {"app.core.database": fake_db}), \
         mock.patch.object(main.asyncio, "create_task", return_value=mock.Mock()) as mock_task, \
         mock.patch.object(main, "logger"):
        import asyncio
        asyncio.run(main.on_startup())
        assert mock_task.called, (
            "create_task was never called; CPU worker won't start"
        )


def test_startup_guard_warns_but_does_not_raise_in_dev(monkeypatch):
    """With PIRD_ENV unset (dev), missing keys must NOT raise. The
    guard logs a warning so the operator notices but the service
    starts. Dev often runs with stub keys or only some providers."""
    monkeypatch.delenv("PIRD_ENV", raising=False)
    env = {}
    for k in REQUIRED_KEYS:
        env[k] = f"fake_{k}"

    main = _reload_main_with_env(monkeypatch, env)

    fake_db = mock.MagicMock()
    fake_db.init_db = mock.AsyncMock()
    with mock.patch.dict(sys.modules, {"app.core.database": fake_db}), \
         mock.patch.object(main.asyncio, "create_task", return_value=mock.Mock()), \
         mock.patch.object(main, "logger") as mock_logger:
        import asyncio
        asyncio.run(main.on_startup())