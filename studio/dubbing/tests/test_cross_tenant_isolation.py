"""PIRD-017 follow-up: cross-tenant isolation on the by-id job path.

The original PIRD-017 contract said the `*Internal` Convex functions
"derive workspaceId server-side from the doc itself". That is tautological
for a by-id lookup: deriving the workspace FROM the doc tells you who owns
the doc, never whether the CALLER is entitled to it. So
`dubbingJobs:getInternal` returned any doc to anyone holding
INTERNAL_API_KEY, and `database_convex.get_job` accepted a `workspace_id`
kwarg it silently ignored (its own comment claimed derivation that the body
never performed).

Effect: a tenant-A user with a valid Clerk JWT who knew a tenant-B job id
could read tenant-B job metadata via GET /video/jobs/{job_id} and obtain a
signed R2 download URL via GET /video/jobs/{job_id}/download.

`get_job` is the single choke point for both routes (video.py:345 and
video.py:364), so the ownership assertion lives there.

Run:
    cd D:/pird/studio/dubbing
    python -m pytest tests/test_cross_tenant_isolation.py -v
"""
from __future__ import annotations

import asyncio
import importlib
import sys

import pytest


@pytest.fixture()
def db(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "test-key-xyz")
    monkeypatch.setenv("PIRD_ENV", "dev")
    sys.modules.pop("app.core.database_convex", None)
    mod = importlib.import_module("app.core.database_convex")
    mod._in_memory_jobs.clear()
    return mod


class _FakeClient:
    """Stands in for ConvexClient. Returns one doc regardless of jobId,
    which is exactly the server behaviour that made the IDOR possible."""

    def __init__(self, doc):
        self.doc = doc
        self.queries = []

    def query(self, name, args):
        self.queries.append((name, args))
        return self.doc


def _job_doc(workspace_id: str, job_id: str = "job-1"):
    return {
        "_id": job_id,
        "legacyId": job_id,
        "workspaceId": workspace_id,
        "status": "completed",
        "progress": 100,
        "resultVideoR2Key": "outputs/secret-tenant-video.mp4",
    }


def test_get_job_refuses_cross_tenant_doc(db):
    """Tenant A asking for tenant B's job must get nothing back."""
    client = _FakeClient(_job_doc("ws-TENANT-B"))
    result = asyncio.run(db.get_job(client, workspace_id="ws-TENANT-A", job_id="job-1"))
    assert result is None, "cross-tenant job leaked to the caller"


def test_get_job_does_not_leak_download_key_cross_tenant(db):
    """The R2 key is the exfiltration primitive — it must never come back."""
    client = _FakeClient(_job_doc("ws-TENANT-B"))
    result = asyncio.run(db.get_job(client, workspace_id="ws-TENANT-A", job_id="job-1"))
    assert not (result or {}).get("result_video_r2_key")


def test_get_job_allows_same_tenant(db):
    client = _FakeClient(_job_doc("ws-TENANT-A"))
    result = asyncio.run(db.get_job(client, workspace_id="ws-TENANT-A", job_id="job-1"))
    assert result is not None
    assert result["workspace_id"] == "ws-TENANT-A"
    assert result["result_video_r2_key"] == "outputs/secret-tenant-video.mp4"


def test_get_job_unscoped_call_still_works(db):
    """Worker/internal paths pass no workspace_id and must keep working."""
    client = _FakeClient(_job_doc("ws-TENANT-B"))
    result = asyncio.run(db.get_job(client, job_id="job-1"))
    assert result is not None
    assert result["workspace_id"] == "ws-TENANT-B"


def test_in_memory_fallback_is_also_scoped(db):
    """The fallback path must not become a bypass when Convex is down."""

    class _Boom:
        def query(self, *a, **k):
            raise RuntimeError("convex unreachable")

    db._in_memory_jobs["job-1"] = {
        "id": "job-1",
        "workspace_id": "ws-TENANT-B",
        "status": "completed",
        "result_video_r2_key": "outputs/secret.mp4",
    }
    leaked = asyncio.run(db.get_job(_Boom(), workspace_id="ws-TENANT-A", job_id="job-1"))
    assert leaked is None, "in-memory fallback leaked cross-tenant"

    own = asyncio.run(db.get_job(_Boom(), workspace_id="ws-TENANT-B", job_id="job-1"))
    assert own is not None


def test_get_job_forwards_workspace_to_convex_for_defense_in_depth(db):
    """The adapter should tell Convex which tenant it expects, so the guard
    also exists server-side rather than only in the Python layer."""
    client = _FakeClient(_job_doc("ws-TENANT-A"))
    asyncio.run(db.get_job(client, workspace_id="ws-TENANT-A", job_id="job-1"))
    assert client.queries, "no query issued"
    _name, args = client.queries[0]
    assert args.get("expectedWorkspaceId") == "ws-TENANT-A"
