import os
import shutil
import logging
import gc
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("mcp.storage")

# Root scratch directory for temporary audio/video processing
SCRATCH_BASE = Path(os.getenv("DOBLAJ_SCRATCH_DIR", "tmp/doblaj_scratch"))
SCRATCH_BASE.mkdir(parents=True, exist_ok=True)


class ScratchManager:
    """Manages the deterministic lifecycle of temporary job files on local disk."""

    @staticmethod
    def get_job_dir(job_id: str) -> Path:
        """Get or create the dedicated scratch directory for a job."""
        job_dir = SCRATCH_BASE / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        return job_dir

    @staticmethod
    def cleanup_job(job_id: str) -> bool:
        """Safely delete all intermediate processing files for a job upon completion/failure."""
        gc.collect()
        job_dir = SCRATCH_BASE / job_id
        if job_dir.exists() and job_dir.is_dir():
            for attempt in range(3):
                try:
                    shutil.rmtree(job_dir)
                    logger.info(f"[SCRATCH CLEANUP] Successfully cleaned up scratch directory for job: {job_id}")
                    return True
                except Exception as e:
                    time.sleep(0.3)
                    gc.collect()
                    if attempt == 2:
                        logger.warning(f"[SCRATCH CLEANUP WARNING] Failed to delete scratch directory {job_dir}: {e}")
                        return False
        return True
