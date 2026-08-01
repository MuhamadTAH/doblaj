"""CLI shim: run the Azure CPU polling worker as a standalone process.

Used by systemd / supervisord / k8s deployments where the worker runs in
its own container, separate from the FastAPI app. When the worker runs
in-process, FastAPI's startup hook spawns it directly and this file is
not used.

Run with:
    python azure_polling_worker.py

The polling logic lives in `app.services.cpu_worker` so both in-process
and standalone paths share one implementation.
"""
import asyncio
import logging

from app.services.cpu_worker import poll_for_gpu_finished_jobs


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )


if __name__ == "__main__":
    _configure_logging()
    try:
        asyncio.run(poll_for_gpu_finished_jobs())
    except KeyboardInterrupt:
        logging.info("[AZURE_WORKER] Interrupted by operator.")