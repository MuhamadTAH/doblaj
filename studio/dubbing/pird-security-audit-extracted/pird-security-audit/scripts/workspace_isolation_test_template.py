"""
Automated isolation tests for Pird's confirmed Convex/Clerk architecture.

Confirmed architecture (see references/architecture.md and the stack_migration
note in findings_ledger.json): Convex does not independently check identity.
Every public Convex function trusts whatever it's handed. Isolation is
enforced entirely at the FastAPI edge, across TWO separate entry points:

  1. Browser -> FastAPI (/video/*, /tts/*, /api/*) -> Convex.
     FastAPI decodes the Clerk JWT, resolves its org_xxx claim to a legacy
     workspace UUID via _resolve_legacy_workspace_id, and passes that UUID
     to Convex as a plain string.

  2. RunPod worker -> FastAPI's internalJobs router (main.py:390,
     INTERNAL_API_KEY-gated) -> Convex.
     This router accepts workspace_id directly from the request body - see
     PIRD-017. test_internal_jobs_rejects_mismatched_workspace below is
     expected to FAIL until that's fixed; that failure is the point, and a
     passing run is the actual verification_method for closing PIRD-017.

Requires: pytest, httpx (pip install --break-system-packages pytest httpx)

ADAPT before running:
  - create_test_tenant(): wire up a real Clerk test org + user, sign in,
    return a TestTenant with a real dubbing_access_token session value.
  - BASE_URL: point at your local FastAPI instance.
  - INTERNAL_API_KEY_VALUE: your dev INTERNAL_API_KEY (never a prod one).
  - The REPLACE_ME values: create a real job under tenant A first via the
    normal browser-facing flow, and capture its job_id.
  - The internalJobs path below is a guess - confirm the real route.
"""
import pytest
import httpx

BASE_URL = "http://localhost:8000"
INTERNAL_API_KEY_VALUE = "REPLACE_ME"  # dev-only value, never a real prod key


class TestTenant:
    def __init__(self, user_id: str, org_id: str, session_cookie: str):
        self.user_id = user_id
        self.org_id = org_id  # Clerk org_xxx
        self.session_cookie = session_cookie  # dubbing_access_token value


def create_test_tenant(label: str) -> TestTenant:
    """TODO: create a real Clerk test org + user, sign in, return a TestTenant
    with a real dubbing_access_token session cookie value."""
    raise NotImplementedError(f"Wire up test-tenant creation for '{label}' before running this suite.")


def cookies_for(tenant: TestTenant) -> dict:
    return {"dubbing_access_token": tenant.session_cookie}


@pytest.fixture(scope="module")
def two_tenants():
    return create_test_tenant("tenant-a"), create_test_tenant("tenant-b")


def test_browser_path_cross_tenant_read_is_blocked(two_tenants):
    """Tenant B must never read tenant A's jobs through the normal browser
    path. This tests FastAPI's Clerk-JWT -> org_xxx -> legacy-UUID resolution
    chain, since Convex itself enforces nothing here - the resolution chain
    IS the isolation boundary. Covers PIRD-001."""
    tenant_a, tenant_b = two_tenants
    job_id = "REPLACE_ME"  # TODO: create a real job under tenant_a first

    with httpx.Client(base_url=BASE_URL) as client:
        for method, path in [
            ("GET", f"/video/{job_id}"),
            ("GET", f"/video/{job_id}/chunks"),
            ("GET", f"/video/{job_id}/translation"),
        ]:
            resp = client.request(method, path, cookies=cookies_for(tenant_b))
            assert resp.status_code in (403, 404), (
                f"{method} {path} returned {resp.status_code} for tenant B reading "
                f"tenant A's job - the JWT-to-workspace_id resolution chain leaked."
            )


def test_unmapped_org_falls_through_safely(two_tenants):
    """An org_xxx with no mapped legacy workspace should not silently resolve
    to someone else's data. Current understanding is _resolve_legacy_workspace_id
    falls through and Convex returns empty (no workspace has that legacyId) -
    this test exists to turn that assumption into something checked, not just
    believed. Covers the second half of PIRD-001."""
    tenant_a, _tenant_b = two_tenants
    job_id = "REPLACE_ME"  # TODO: a real job_id belonging to tenant_a

    # TODO: a session value whose org_xxx claim deliberately has no
    # corresponding legacy workspace mapping.
    fake_session_with_unmapped_org = "REPLACE_ME"

    with httpx.Client(base_url=BASE_URL) as client:
        resp = client.get(
            f"/video/{job_id}",
            cookies={"dubbing_access_token": fake_session_with_unmapped_org},
        )
        assert resp.status_code in (403, 404), (
            f"Expected an unmapped org_xxx to see nothing, got {resp.status_code}. "
            f"If this ever returns 200 with real data, the fallback path is not safe."
        )


def test_internal_jobs_rejects_mismatched_workspace(two_tenants):
    """THE CONFIRMED GAP (PIRD-017): the internalJobs router currently accepts
    workspace_id straight from the request body. This test is EXPECTED TO FAIL
    until that's fixed - a passing run here is the actual verification for
    PIRD-017, not a read-through of the code."""
    tenant_a, tenant_b = two_tenants
    job_id = "REPLACE_ME"  # TODO: a real job_id belonging to tenant_a

    with httpx.Client(base_url=BASE_URL) as client:
        resp = client.post(
            "/internal/jobs/update",  # TODO: confirm the real internalJobs path
            headers={"X-Internal-Api-Key": INTERNAL_API_KEY_VALUE},
            json={"job_id": job_id, "workspace_id": tenant_b.org_id, "status": "processing"},
        )
        assert resp.status_code in (403, 404), (
            f"internalJobs accepted a workspace_id ({tenant_b.org_id}) that doesn't "
            f"match job {job_id}'s actual owning tenant ({tenant_a.org_id}), and "
            f"returned {resp.status_code}. This IS PIRD-017: fix by deriving "
            f"workspace_id server-side from the job_id's own record instead of "
            f"trusting the caller's body."
        )


def test_tts_voices_list_is_intentionally_global(two_tenants):
    """ttsVoices:list is accepted as global, non-tenant-scoped data (PIRD-018).
    This test exists so a future 'fix' doesn't accidentally break intentional
    behavior - it should keep returning results for any authenticated caller,
    not start filtering by workspace."""
    tenant_a, _tenant_b = two_tenants
    with httpx.Client(base_url=BASE_URL) as client:
        resp = client.get("/tts/voices", cookies=cookies_for(tenant_a))
        assert resp.status_code == 200, "ttsVoices:list should stay globally readable by design."
