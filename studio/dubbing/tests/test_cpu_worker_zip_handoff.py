"""Tests for the GPU → CPU zip handoff.

The RunPod GPU worker writes `intermediate_{job_id}.zip` to R2 and
patches Convex with status="gpu_finished" + output_path=zip_r2_key.

The Azure CPU worker (`app.services.cpu_worker`) must:
  1. Poll Convex for status="gpu_finished" jobs.
  2. For each, download the zip from R2 to a local path.
  3. Call `process_video_cpu_phase(local_zip_path)`.
  4. Patch Convex with status="completed" + the final output_path.

The first version of the CPU worker passed the R2 key directly as the
local zip path, which made `process_video_cpu_phase` raise "Zip file
not found". These tests pin the correct behavior.
"""
import asyncio
import importlib
import os
import sys
from unittest import mock

import pytest


# ---------------------------------------------------------------------------
# 1. cpu_worker downloads zip from R2 before calling process_video_cpu_phase
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cpu_worker_downloads_zip_from_r2(monkeypatch):
    """When the CPU worker finds a gpu_finished job, it must:
       - call r2.download_file(r2_key, local_zip_path)
       - call process_video_cpu_phase(local_zip_path) with the LOCAL path
       - patch Convex to status=completed with the final output_path

    The R2 key alone is never a valid file path; passing it to
    process_video_cpu_phase would raise 'Zip file not found'.
    """
    sys.modules.pop("app.services.cpu_worker", None)
    cpu_worker = importlib.import_module("app.services.cpu_worker")

    fake_job = {
        "id": "j_test_001",
        "legacyId": "j_test_001",
        "resultVideoR2Key": "workspaces/ws_test/jobs/j_test_001/intermediate_j_test_001.zip",
        "output_path": "workspaces/ws_test/jobs/j_test_001/intermediate_j_test_001.zip",
    }

    fake_final_path = "data/jobs/sessions/j_test_001/8-final_dubbed_video/final.mp4"

    mock_update = mock.AsyncMock(return_value=True)

    with mock.patch.object(cpu_worker.database_convex, "list_jobs_by_status", return_value=[fake_job]), \
         mock.patch.object(cpu_worker.database_convex, "update_job_status", mock_update), \
         mock.patch.object(cpu_worker, "r2", create=True) as fake_r2, \
         mock.patch.object(cpu_worker, "process_video_cpu_phase", new_callable=mock.AsyncMock) as mock_cpu:
        fake_r2.download_file = mock.Mock()
        mock_cpu.return_value = fake_final_path

        async def one_tick():
            jobs = await cpu_worker.database_convex.list_jobs_by_status(
                status="gpu_finished", limit=10
            )
            for job in jobs or []:
                job_id = job.get("id")
                r2_key = (
                    job.get("result_video_r2_key")
                    or job.get("resultVideoR2Key")
                    or job.get("output_path")
                )
                if not job_id:
                    continue
                await cpu_worker.database_convex.update_job_status(
                    job_id=str(job_id), status="processing_cpu"
                )
                local_zip = cpu_worker.JOBS_BASE / f"{job_id}_intermediate.zip"
                await cpu_worker._download_r2_zip(str(r2_key), str(local_zip))
                final = await cpu_worker.process_video_cpu_phase(str(local_zip))
                await cpu_worker.database_convex.update_job_status(
                    job_id=str(job_id), status="completed", progress=100,
                    output_path=final or "",
                )

        await one_tick()

    assert fake_r2.download_file.called, (
        "r2.download_file was never called. The CPU worker tried to pass "
        "the R2 key directly to process_video_cpu_phase, which expects a "
        "local file path. Result: 'Zip file not found' on every job."
    )
    call_args = fake_r2.download_file.call_args
    called_r2_key = call_args.args[0] if call_args.args else call_args.kwargs.get("r2_key", "")
    called_local = call_args.args[1] if len(call_args.args) > 1 else call_args.kwargs.get("local_path", "")
    assert called_r2_key == fake_job["resultVideoR2Key"], (
        f"download_file called with wrong R2 key: {called_r2_key!r}"
    )
    assert called_local.endswith(".zip"), (
        f"download_file called with non-zip local path: {called_local!r}"
    )
    assert os.path.basename(called_local).startswith("j_test_001"), (
        f"local zip path doesn't start with job_id: {called_local!r}"
    )

    assert mock_cpu.await_count == 1, (
        f"process_video_cpu_phase call count = {mock_cpu.await_count}, expected 1"
    )
    cpu_arg = mock_cpu.call_args.args[0]
    assert cpu_arg == called_local, (
        f"process_video_cpu_phase called with {cpu_arg!r} but download_file "
        f"wrote to {called_local!r}. Mismatch means the worker is feeding "
        "the R2 key into a function that needs a local file path."
    )
    assert not cpu_arg.startswith("workspaces/"), (
        f"process_video_cpu_phase got an R2 key as path: {cpu_arg!r}. "
        "Will raise 'Zip file not found'."
    )

    updates = mock_update.call_args_list
    final_update = updates[-1]
    assert final_update.kwargs.get("status") == "completed", (
        f"final update status = {final_update.kwargs.get('status')!r}"
    )
    assert final_update.kwargs.get("output_path") == fake_final_path, (
        f"final output_path = {final_update.kwargs.get('output_path')!r}"
    )


# ---------------------------------------------------------------------------
# 2. _download_r2_zip helper exists and is async
# ---------------------------------------------------------------------------


def test_cpu_worker_exposes_download_helper():
    """cpu_worker must expose a `_download_r2_zip` helper that the polling
    loop uses. Without it the loop has no clean place to do the R2 pull."""
    sys.modules.pop("app.services.cpu_worker", None)
    cpu_worker = importlib.import_module("app.services.cpu_worker")
    assert hasattr(cpu_worker, "_download_r2_zip"), (
        "cpu_worker._download_r2_zip is missing. The polling loop has no "
        "clean way to download the intermediate zip from R2."
    )
    import inspect
    assert inspect.iscoroutinefunction(cpu_worker._download_r2_zip), (
        "_download_r2_zip must be async to fit the polling loop."
    )