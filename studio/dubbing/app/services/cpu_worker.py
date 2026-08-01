"""Azure CPU polling worker for the dubbing pipeline.

Polled from FastAPI startup hook (see main.py `on_startup`). Wakes every
5s, asks Convex for jobs in status="gpu_finished", downloads the
intermediate zip from R2, runs the CPU phase (transcribe → translate →
TTS → mux), and patches Convex with status="completed".

The legacy `azure_polling_worker.py` CLI shim in the repo root forwards
to this function for process-manager deployments (systemd, supervisord).
"""
import asyncio
import logging
from pathlib import Path

from app.core import database_convex
from app.services import r2
from app.services.video_worker_vcta import process_video_cpu_phase

logger = logging.getLogger(__name__)


# Where downloaded intermediate zips live before being unzipped by
# process_video_cpu_phase. Mirrors the convention in runpod_worker.py.
JOBS_BASE = Path("data/jobs/sessions")


async def _download_r2_zip(r2_key: str, local_path: str) -> None:
    """Pull the RunPod-produced intermediate zip from R2 to local disk.

    `r2.download_file` is synchronous; run it in a worker thread so the
    event loop stays responsive.
    """
    Path(local_path).parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(r2.download_file, r2_key, local_path)
    logger.info("[AZURE_WORKER] Downloaded %s -> %s", r2_key, local_path)


async def poll_for_gpu_finished_jobs() -> None:
    """Loop forever, draining the gpu_finished queue.

    On every tick:
      1. Ask Convex for up to 10 jobs with status="gpu_finished".
      2. For each: download intermediate zip from R2 → local disk.
      3. Lock via Convex patch (atomic) so concurrent pollers don't
         double-process.
      4. Run CPU phase (unzip → transcribe → translate → TTS → mux).
      5. Patch to "completed" with progress=100 + final output_path,
         or "failed" on error.

    Sleeps 5s between ticks. Exits cleanly on CancelledError so the
    FastAPI shutdown hook can stop it without leaving dangling tasks.
    """
    JOBS_BASE.mkdir(parents=True, exist_ok=True)
    logger.info("[AZURE_WORKER] Starting Azure CPU polling worker...")
    try:
        while True:
            try:
                jobs = await database_convex.list_jobs_by_status(
                    status="gpu_finished", limit=10
                )
            except Exception as e:
                logger.error("[AZURE_WORKER] list_jobs_by_status failed: %s", e)
                await asyncio.sleep(5)
                continue

            for job in jobs or []:
                job_id = job.get("id") or job.get("_id") or job.get("legacyId")
                r2_key = (
                    job.get("result_video_r2_key")
                    or job.get("resultVideoR2Key")
                    or job.get("output_path")
                )
                if not job_id:
                    continue

                logger.info(
                    "[AZURE_WORKER] Found job %s ready for CPU phase.", job_id
                )

                locked = await database_convex.update_job_status(
                    job_id=str(job_id), status="processing_cpu"
                )
                if not locked:
                    logger.warning(
                        "[AZURE_WORKER] Failed to lock job %s. Skipping.", job_id
                    )
                    continue

                local_zip = str(JOBS_BASE / f"{job_id}_intermediate.zip")

                try:
                    if r2_key:
                        await _download_r2_zip(str(r2_key), local_zip)
                    else:
                        logger.warning(
                            "[AZURE_WORKER] Job %s has no R2 key; "
                            "assuming local zip at %s",
                            job_id,
                            local_zip,
                        )

                    logger.info(
                        "[AZURE_WORKER] Starting CPU phase for %s. Local zip: %s",
                        job_id,
                        local_zip,
                    )
                    final_path = await process_video_cpu_phase(local_zip)
                    await database_convex.update_job_status(
                        job_id=str(job_id),
                        status="completed",
                        progress=100,
                        output_path=final_path or "",
                    )
                    logger.info(
                        "[AZURE_WORKER] Job %s completed successfully. Output: %s",
                        job_id,
                        final_path,
                    )
                except Exception as e:
                    logger.exception(
                        "[AZURE_WORKER] Job %s failed during CPU phase: %s",
                        job_id,
                        e,
                    )
                    try:
                        await database_convex.update_job_status(
                            job_id=str(job_id),
                            status="failed",
                            error=f"CPU phase error: {e}",
                        )
                    except Exception:
                        logger.exception(
                            "[AZURE_WORKER] Could not mark job %s failed", job_id
                        )

            await asyncio.sleep(5)
    except asyncio.CancelledError:
        logger.info("[AZURE_WORKER] Polling loop cancelled (shutdown).")
        raise