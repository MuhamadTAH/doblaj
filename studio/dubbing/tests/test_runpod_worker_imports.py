"""Tests for the RunPod Serverless worker import surface.

`runpod_worker.py` is the entry point deployed to RunPod's Serverless
endpoint. It runs in a cold-start container, NOT in the FastAPI host's
process. Anything it imports must exist in the deployed image.

After PIRD-026 removed the Supabase adapter (`app.core.db` no longer
exposes `_get_service_role_client`), the worker MUST be rewritten to
use `app.core.database_convex` exclusively.
"""
import importlib
import sys

import pytest

try:
    import runpod  # noqa: F401
    HAS_RUNPOD = True
except ImportError:
    HAS_RUNPOD = False

require_runpod = pytest.mark.skipif(
    not HAS_RUNPOD,
    reason="runpod SDK not installed locally; covered by the static check below",
)


@require_runpod
def test_runpod_worker_imports_succeed():
    """The RunPod worker must import cleanly. If it tries to import a
    removed Supabase symbol, the cold-start container will crash before
    serving any request -- silent failure mode that costs RunPod credits
    on every retry."""
    sys.modules.pop("runpod_worker", None)
    try:
        mod = importlib.import_module("runpod_worker")
    except ImportError as e:
        raise AssertionError(
            f"runpod_worker.py failed to import: {e}. "
            "It still references the removed Supabase adapter "
            "(`from app.core.db import _get_service_role_client`). "
            "The deployed RunPod container will crash on cold start."
        )
    assert mod is not None


def test_runpod_worker_does_not_import_supabase_adapter():
    """Static check: the source must not import the removed Supabase path.
    Catches the bug even before import (e.g. if `runpod` is missing locally)."""
    import os
    src_path = os.path.join(
        os.path.dirname(__file__), "..", "runpod_worker.py"
    )
    src_path = os.path.abspath(src_path)
    with open(src_path, "r", encoding="utf-8") as fh:
        src = fh.read()

    assert "from app.core.db import _get_service_role_client" not in src, (
        "runpod_worker.py still imports _get_service_role_client from the "
        "removed Supabase adapter. Rewrite to use database_convex."
    )
    assert "_get_service_role_client" not in src, (
        "runpod_worker.py still references _get_service_role_client. "
        "Rewrite to use database_convex."
    )
    assert "from app.core import database_convex" in src or "database_convex" in src, (
        "runpod_worker.py doesn't import database_convex. The worker must "
        "patch Convex job status via the Convex adapter."
    )


@require_runpod
def test_runpod_worker_handler_signature_intact():
    """The handler exposed to RunPod must be a callable named `handler`
    accepting a dict-like event. RunPod Serverless invokes it directly."""
    sys.modules.pop("runpod_worker", None)
    mod = importlib.import_module("runpod_worker")
    assert hasattr(mod, "handler"), "runpod_worker.handler is missing"
    import inspect
    sig = inspect.signature(mod.handler)
    assert "event" in sig.parameters, (
        f"handler must take an event arg; signature = {sig}"
    )