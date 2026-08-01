"""
PIRD-001 verification: prove `_resolve_legacy_workspace_id` returns an
empty string for an `org_xxx` value that has no Convex mapping — never
the raw `org_xxx` string.

The isolation contract depends on Convex receiving an empty workspaceId
on lookup so it returns no rows. If a malformed Clerk JWT (or one from
an unmapped org) yielded a non-empty string, it could collide with a
real workspace's legacyId.

Run:
    cd D:/Pird/studio/dubbing
    python -m pytest tests/test_workspace_isolation.py -v
"""
from __future__ import annotations

import asyncio
import importlib
import sys
from unittest.mock import MagicMock, patch

import pytest


def _reload():
    sys.modules.pop("app.auth.clerk_auth", None)
    if "app.auth" in sys.modules:
        sys.modules.pop("app.auth", None)
    return importlib.import_module("app.auth.clerk_auth")


def test_resolve_unmapped_org_auto_provisions(monkeypatch):
    """An org_xxx with no row in Convex used to return ''. Now the
    resolver auto-provisions a workspace via
    `workspaces:createForOwnerInternal` so first sign-in completes
    instead of looping on an empty workspaceId claim.

    Security contract that MUST still hold:
      - the raw `org_xxx` value is never returned (collision risk
        against a real workspace's legacyId)
      - on auto-provision failure (mutation raises), the function
        falls back to '' (fail-closed)
    """
    mod = _reload()
    fake_mod = type(sys)("fake_convex")

    class _AutoProvisionClient:
        def __init__(self):
            self.queries = []
            self.mutations = []

        def query(self, name, args):
            self.queries.append((name, args))
            return None  # no existing workspace

        def mutation(self, name, args):
            self.mutations.append((name, args))
            return {"legacyId": "ws-newly-provisioned-001"}

    auto = _AutoProvisionClient()
    fake_mod.ConvexClient = lambda *a, **k: auto
    sys.modules["convex"] = fake_mod

    result = asyncio.run(mod._resolve_legacy_workspace_id("org_orphan_xyz", "user_123"))

    # The security contract: raw org_xxx never leaks through.
    assert result != "org_orphan_xyz", (
        f"raw org_xxx leaked through: {result!r}"
    )
    # And we either got a real legacyId from auto-provision, or empty on failure.
    assert result == "ws-newly-provisioned-001", (
        f"expected auto-provisioned legacyId, got {result!r}"
    )
    # And the create mutation was actually called with the right args.
    assert auto.mutations, "createForOwnerInternal was not called"
    name, args = auto.mutations[0]
    assert name == "workspaces:createForOwnerInternal"
    assert args["ownerUserId"] == "user_123"
    assert args["orgId"] == "org_orphan_xyz"


def test_resolve_unmapped_org_provision_failure_returns_empty(monkeypatch):
    """If the auto-provision mutation throws (Convex down, bad key,
    schema error), the resolver MUST fall back to '' so the caller
    surfaces a 403 rather than letting the user proceed with an
    unresolvable workspaceId claim."""
    mod = _reload()
    fake_mod = type(sys)("fake_convex")

    class _BoomClient:
        def query(self, *a, **k):
            return None

        def mutation(self, *a, **k):
            raise RuntimeError("convex unreachable")

    fake_mod.ConvexClient = lambda *a, **k: _BoomClient()
    sys.modules["convex"] = fake_mod

    result = asyncio.run(mod._resolve_legacy_workspace_id("org_orphan_xyz", "user_123"))
    assert result == "", (
        f"auto-provision failure must fail-closed to empty string, got {result!r}"
    )
    assert result != "org_orphan_xyz", "raw org_xxx leaked through on failure path"


def test_resolve_mapped_org_returns_legacy_id():
    mod = _reload()
    fake_mod = type(sys)("fake_convex")
    fake_client = MagicMock()
    fake_client.query.return_value = {"legacyId": "ws-real-legacy-id"}
    fake_mod.ConvexClient = lambda *a, **k: fake_client
    sys.modules["convex"] = fake_mod

    result = asyncio.run(mod._resolve_legacy_workspace_id("org_mapped", "user_456"))
    assert result == "ws-real-legacy-id"


def test_resolve_empty_input_returns_empty():
    mod = _reload()
    result = asyncio.run(mod._resolve_legacy_workspace_id("", "user_789"))
    assert result == ""


def test_resolve_non_org_id_passes_through():
    mod = _reload()
    # A bare UUID-shaped string starting with "ws_" should pass through
    # untouched.
    result = asyncio.run(mod._resolve_legacy_workspace_id("ws-uuid-123", "user_x"))
    assert result == "ws-uuid-123"
