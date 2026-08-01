"""
PIRD-017 verification: prove the Python adapter never forwards
`workspaceId` to `*Internal` Convex calls. Server-side derivation is
the only thing standing between a single shared INTERNAL_API_KEY and
cross-tenant writes.

Run:
    cd D:/Pird/studio/dubbing
    python -m pytest tests/test_internal_workspace_isolation.py -v
"""
from __future__ import annotations

import importlib
import os
import sys
import types

import pytest


def _reload_module(monkeypatch):
    """Reload database_convex with a fresh env each test."""
    sys.modules.pop("app.core.database_convex", None)
    if "app.core" in sys.modules:
        sys.modules.pop("app.core", None)
    return importlib.import_module("app.core.database_convex")


def test_internal_args_does_not_carry_workspace_id(monkeypatch):
    """`_internal_args` returns only __internalApiKey + extra. Callers must
    not pass a `workspaceId` key."""
    monkeypatch.setenv("INTERNAL_API_KEY", "test-key-xyz")
    db = _reload_module(monkeypatch)
    args = db._internal_args({"jobId": "job-abc"})
    assert args == {"__internalApiKey": "test-key-xyz", "jobId": "job-abc"}
    assert "workspaceId" not in args
    assert "workspace_id" not in args


def test_internal_args_with_legacy_id_only(monkeypatch):
    """The minutes helpers should be called with `legacyId`, not
    `workspaceId`."""
    monkeypatch.setenv("INTERNAL_API_KEY", "test-key-xyz")
    db = _reload_module(monkeypatch)
    args = db._internal_args({"legacyId": "ws-uuid-123", "delta": 5})
    assert args["legacyId"] == "ws-uuid-123"
    assert "workspaceId" not in args


def test_internal_args_raises_in_prod_when_unset(monkeypatch):
    monkeypatch.delenv("INTERNAL_API_KEY", raising=False)
    monkeypatch.setenv("PIRD_ENV", "prod")
    db = _reload_module(monkeypatch)
    with pytest.raises(RuntimeError):
        db._internal_args({"jobId": "x"})


def test_internal_args_warns_in_dev_when_unset(monkeypatch, caplog):
    monkeypatch.delenv("INTERNAL_API_KEY", raising=False)
    monkeypatch.setenv("PIRD_ENV", "dev")
    db = _reload_module(monkeypatch)
    # Should not raise; should return dict with empty key.
    args = db._internal_args({"jobId": "x"})
    assert args["__internalApiKey"] == ""
