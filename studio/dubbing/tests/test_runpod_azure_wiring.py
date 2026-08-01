"""Tests for RunPod GPU + Azure CPU worker wiring (Option A).

Three contracts being verified:

1. When RUNPOD_ENDPOINT_ID + RUNPOD_API_KEY are set, `create_job` POSTs to
   `https://api.runpod.ai/v2/{endpoint}/run` (api.runpod.io returns 404).
2. When `RUNPOD_ENDPOINT_ID` is unset, `create_job` falls back to local
   background processing instead of raising.
3. Azure CPU worker is spawned as an asyncio.Task on FastAPI startup,
   and uses `database_convex` (not the removed Supabase adapter).
"""
import asyncio
import importlib
import os
import sys
from unittest import mock

import pytest


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _reload_video_module(monkeypatch):
    """Reload app.api.routes.video with patched env vars so the module-level
    `RUNPOD_ENDPOINT_ID = os.getenv(...)` reads the patched value."""
    sys.modules.pop("app.api.routes.video", None)
    return importlib.import_module("app.api.routes.video")


def _reload_main_module(monkeypatch):
    sys.modules.pop("main", None)
    return importlib.import_module("main")


# ---------------------------------------------------------------------------
# 1. RunPod trigger fires when env vars present
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_job_posts_to_runpod_when_endpoint_configured(monkeypatch):
    """When RUNPOD_ENDPOINT_ID + RUNPOD_API_KEY are set, create_job must
    POST to api.runpod.ai/v2/{endpoint}/run with a Bearer token, and NOT
    fall through to local background processing."""
    monkeypatch.setenv("RUNPOD_ENDPOINT_ID", "ep-test-1234")
    monkeypatch.setenv("RUNPOD_API_KEY", "rpa_test_key")

    video = _reload_video_module(monkeypatch)

    fake_user = mock.Mock()
    fake_user.user_id = "u_test"
    fake_user.workspace_id = "w_test"
    fake_user.access_token = "tok"

    fake_job = {
        "id": "j_test",
        "status": "pending",
        "progress": 0,
        "resultVideoR2Key": "",
        "created_at": "2026-07-31T00:00:00Z",
        "updated_at": "2026-07-31T00:00:00Z",
    }

    captured_trigger = {}

    def _capture_bg_task(fn, *args, **kwargs):
        captured_trigger["fn"] = fn
        captured_trigger["args"] = args
        captured_trigger["kwargs"] = kwargs

    # httpx.AsyncClient.post is defined on a base class and bypasses
    # class-attribute patches. Patch the AsyncClient class itself so any
    # `httpx.AsyncClient(...)` returns our fake client.
    mock_response = mock.Mock(status_code=200)
    mock_response.raise_for_status = mock.Mock()
    mock_response.json = mock.AsyncMock(return_value={"id": "rp_job_1"})
    fake_client = mock.Mock()
    fake_client.post = mock.AsyncMock(return_value=mock_response)
    fake_client.__aenter__ = mock.AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = mock.AsyncMock(return_value=None)

    def _fake_async_client(*args, **kwargs):
        return fake_client

    with mock.patch.object(video, "_bounded_read", return_value=b"\x00" * 1024), \
         mock.patch.object(video, "get_video_duration", return_value=30.0), \
         mock.patch.object(video, "_check_voice_recording_consent", return_value=None), \
         mock.patch("app.api.routes.video.require_user", return_value=fake_user), \
         mock.patch("app.core.db.get_user_client", return_value=mock.Mock()), \
         mock.patch("app.core.db.get_workspace_minutes", return_value=999999), \
         mock.patch("app.core.db.create_job", return_value=fake_job), \
         mock.patch.object(video, "worker_process_video_job") as mock_local, \
         mock.patch("app.api.routes.video.httpx.AsyncClient", _fake_async_client), \
         mock.patch("app.services.r2.R2_ENDPOINT", ""), \
         mock.patch("app.services.r2.upload_file"):
        fake_file = mock.Mock()
        fake_file.filename = "test.mp4"
        fake_file.content_type = "video/mp4"
        fake_file.read = mock.AsyncMock(side_effect=[b"\x00" * 1024, b""])
        fake_file.close = mock.Mock()

        fake_bg = mock.Mock()
        fake_bg.add_task = mock.Mock(side_effect=_capture_bg_task)

        try:
            await video.create_job(
                request=mock.Mock(),
                file=fake_file,
                user=fake_user,
                voice_id=None,
                category=None,
                entity=None,
                background_tasks=fake_bg,
            )
        except Exception:
            pass

        # Run the captured trigger synchronously INSIDE the patch context
        # so the closure's `httpx` reference still points at the fake class.
        assert "fn" in captured_trigger, (
            "create_job did not call background_tasks.add_task at all. "
            "Either the orchestrator branch was skipped or BackgroundTasks is mocked wrong."
        )
        trigger_fn = captured_trigger["fn"]
        if asyncio.iscoroutinefunction(trigger_fn):
            await trigger_fn()
        else:
            result = trigger_fn()
            if asyncio.iscoroutine(result):
                await result

    assert fake_client.post.await_count == 1, (
        f"Expected 1 POST to RunPod, got {fake_client.post.await_count}. "
        "Either the gate `if False and ...` is still in place, or the URL is wrong."
    )
    called_url = (
        fake_client.post.call_args.args[0]
        if fake_client.post.call_args.args
        else fake_client.post.call_args.kwargs.get("url", "")
    )
    assert "api.runpod.ai/v2/" in called_url, (
        f"RunPod URL must use api.runpod.ai/v2/{{endpoint}}/run, got {called_url!r}. "
        "api.runpod.io returns 404 -- the base is .ai for /v2/."
    )
    assert "ep-test-1234" in called_url, f"Endpoint ID missing from URL: {called_url!r}"
    assert mock_local.call_count == 0, (
        f"Local worker was scheduled {mock_local.call_count}x alongside RunPod; "
        "should be one or the other."
    )


# ---------------------------------------------------------------------------
# 5. R2 source upload fires when RunPod is configured
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_job_uploads_source_to_r2_for_runpod(monkeypatch):
    """When RUNPOD_ENDPOINT_ID + R2_ENDPOINT are set, create_job MUST
    upload the source video to R2 so the RunPod worker can pull it.
    Without this step, the worker has nothing to process."""
    monkeypatch.setenv("RUNPOD_ENDPOINT_ID", "ep-test-r2")
    monkeypatch.setenv("RUNPOD_API_KEY", "rpa_test_key")
    monkeypatch.setenv("R2_ENDPOINT", "https://fake.r2.cloudflarestorage.com")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "fake_ak")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "fake_sk")
    monkeypatch.setenv("R2_BUCKET", "fake-bucket")

    video = _reload_video_module(monkeypatch)

    fake_user = mock.Mock()
    fake_user.user_id = "u_test"
    fake_user.workspace_id = "w_test"
    fake_user.access_token = "tok"

    fake_job = {
        "id": "j_r2",
        "status": "pending",
        "progress": 0,
        "resultVideoR2Key": "",
        "created_at": "2026-07-31T00:00:00Z",
        "updated_at": "2026-07-31T00:00:00Z",
    }

    with mock.patch.object(video, "_bounded_read", return_value=b"\x00" * 1024), \
         mock.patch.object(video, "get_video_duration", return_value=30.0), \
         mock.patch.object(video, "_check_voice_recording_consent", return_value=None), \
         mock.patch("app.api.routes.video.require_user", return_value=fake_user), \
         mock.patch("app.core.db.get_user_client", return_value=mock.Mock()), \
         mock.patch("app.core.db.get_workspace_minutes", return_value=999999), \
         mock.patch("app.core.db.create_job", return_value=fake_job), \
         mock.patch("app.services.r2.upload_file", new_callable=mock.Mock()) as mock_upload, \
         mock.patch("app.services.r2.R2_ENDPOINT", "https://fake.r2.cloudflarestorage.com"), \
         mock.patch("app.services.r2.dubbing_key", return_value="workspaces/w_test/jobs/j_r2/source.mp4"):

        fake_file = mock.Mock()
        fake_file.filename = "test.mp4"
        fake_file.content_type = "video/mp4"
        fake_file.read = mock.AsyncMock(side_effect=[b"\x00" * 1024, b""])
        fake_file.close = mock.Mock()

        try:
            await video.create_job(
                request=mock.Mock(),
                file=fake_file,
                user=fake_user,
                voice_id=None,
                category=None,
                entity=None,
                background_tasks=mock.Mock(add_task=mock.Mock()),
            )
        except Exception:
            pass

    assert mock_upload.called, (
        "r2.upload_file was NEVER called when RUNPOD_ENDPOINT_ID is set. "
        "The RunPod worker has nothing to download. Source upload must "
        "happen before the RunPod trigger fires."
    )
    call_args = mock_upload.call_args
    called_r2_key = call_args.args[0] if call_args.args else call_args.kwargs.get("r2_key", "")
    assert called_r2_key == "workspaces/w_test/jobs/j_r2/source.mp4", (
        f"r2.upload_file called with unexpected key: {called_r2_key!r}"
    )


# ---------------------------------------------------------------------------
# 2. Local fallback when RunPod not configured
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_job_falls_back_to_local_when_runpod_unset(monkeypatch):
    monkeypatch.delenv("RUNPOD_ENDPOINT_ID", raising=False)
    monkeypatch.delenv("RUNPOD_API_KEY", raising=False)

    video = _reload_video_module(monkeypatch)

    fake_user = mock.Mock()
    fake_user.user_id = "u_test"
    fake_user.workspace_id = "w_test"
    fake_user.access_token = "tok"

    fake_job = {
        "id": "j_local",
        "status": "pending",
        "progress": 0,
        "resultVideoR2Key": "",
        "created_at": "2026-07-31T00:00:00Z",
        "updated_at": "2026-07-31T00:00:00Z",
    }

    captured_task = {}

    def _capture(fn, *args, **kwargs):
        captured_task["fn"] = fn
        captured_task["args"] = args

    with mock.patch.object(video, "_bounded_read", return_value=b"\x00" * 1024), \
         mock.patch.object(video, "get_video_duration", return_value=30.0), \
         mock.patch.object(video, "_check_voice_recording_consent", return_value=None), \
         mock.patch("app.api.routes.video.require_user", return_value=fake_user), \
         mock.patch("app.core.db.get_user_client", return_value=mock.Mock()), \
         mock.patch("app.core.db.get_workspace_minutes", return_value=999999), \
         mock.patch("app.core.db.create_job", return_value=fake_job), \
         mock.patch.object(video, "worker_process_video_job") as mock_local, \
         mock.patch("httpx.AsyncClient.post", new_callable=mock.AsyncMock) as mock_post:
        fake_file = mock.Mock()
        fake_file.filename = "test.mp4"
        fake_file.content_type = "video/mp4"
        fake_file.read = mock.AsyncMock(side_effect=[b"\x00" * 1024, b""])
        fake_file.close = mock.Mock()

        fake_bg = mock.Mock()
        fake_bg.add_task = mock.Mock(side_effect=_capture)

        try:
            await video.create_job(
                request=mock.Mock(),
                file=fake_file,
                user=fake_user,
                voice_id=None,
                category=None,
                entity=None,
                background_tasks=fake_bg,
            )
        except Exception as e:
            pytest.fail(
                f"create_job raised with no RunPod config (should fall back to local): {e}"
            )

    assert mock_post.await_count == 0, "RunPod POST was attempted with no endpoint configured"
    assert "fn" in captured_task, "create_job did not schedule any background task"
    # Local fallback passes worker_process_video_job as the callable.
    assert captured_task["fn"] is mock_local, (
        f"Fallback path scheduled wrong callable: {captured_task['fn']!r}. "
        "Expected worker_process_video_job (the local GPU+CPU pipeline)."
    )


# ---------------------------------------------------------------------------
# 3. Azure CPU worker spawned on FastAPI startup
# ---------------------------------------------------------------------------


def test_azure_cpu_worker_spawned_on_startup(monkeypatch):
    """main.py's startup hook must spawn the Azure CPU polling worker as a
    background asyncio.Task. Without it, jobs pile up in gpu_finished.

    Strategy: import main.py, find the registered @app.on_event("startup")
    handlers by walking the source file. We avoid mocking FastAPI because
    main.py also imports fastapi.staticfiles and starlette, which collides
    with module-level mocking."""
    src_path = os.path.join(
        os.path.dirname(__file__), "..", "main.py"
    )
    src_path = os.path.abspath(src_path)
    src = open(src_path, "r", encoding="utf-8").read()

    # Must register an @app.on_event("startup") handler.
    assert '@app.on_event("startup")' in src, (
        "No @app.on_event('startup') handler found in main.py. "
        "The Azure CPU worker will never spawn."
    )

    # The startup handler must import the polling function and create a Task.
    # Find the function body by slicing after the decorator.
    import re
    m = re.search(
        r'@app\.on_event\("startup"\)\s*\nasync def on_startup\(\):\s*\n(.*?)(?=\n@app\.|\nclass |\Z)',
        src,
        re.DOTALL,
    )
    assert m, "Couldn't locate on_startup() body."
    body = m.group(1)
    assert "poll_for_gpu_finished_jobs" in body or "cpu_worker" in body, (
        "on_startup() doesn't import the CPU polling function. "
        "Either the worker is never spawned, or the import is missing."
    )
    assert "asyncio.create_task" in body, (
        "on_startup() must call asyncio.create_task() to run the worker "
        "concurrently without blocking the event loop."
    )

    # Must register a shutdown handler too (otherwise the worker leaks).
    assert '@app.on_event("shutdown")' in src, (
        "No @app.on_event('shutdown') handler found. The CPU worker task "
        "will leak across app restarts."
    )


# ---------------------------------------------------------------------------
# 4. Azure worker uses database_convex, NOT removed Supabase adapter
# ---------------------------------------------------------------------------


def test_azure_worker_uses_database_convex():
    """The Azure CPU worker must import from app.core.database_convex
    (the Convex adapter), NOT from app.core.db (which has Supabase bits
    removed under PIRD-026)."""
    for path in [
        "studio/dubbing/app/services/cpu_worker.py",
        "studio/dubbing/azure_polling_worker.py",
    ]:
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as fh:
            src = fh.read()
        assert "database_convex" in src, (
            f"{path} does not import database_convex. The worker will crash "
            "trying to read jobs in Convex after the GPU phase finishes."
        )
        # PIRD-026 removed Supabase. The legacy _get_service_role_client is
        # gone in prod. Any worker still importing it from app.core.db crashes.
        assert "_get_service_role_client" not in src, (
            f"{path} still imports _get_service_role_client from the removed "
            "Supabase adapter. That function is gone in prod (PIRD-026) — "
            "rewrite the worker to use database_convex exclusively."
        )
        assert "from app.core import db" not in src, (
            f"{path} still imports the old app.core.db module, which contains "
            "the deleted Supabase path. Use app.core.database_convex instead."
        )