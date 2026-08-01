import os
import sys
import signal
import logging
from typing import Optional, Any

logger = logging.getLogger(__name__)

class JobCancelledRefundException(Exception):
    """Exception raised when a job is killed due to a workspace refund fraud lockout."""
    pass

class InfrastructureKillSwitch:
    """Active kill switch for compute tasks upon refund/fraud lock."""

    @staticmethod
    async def verify_job_or_terminate(job_id: str, workspace_id: str, active_process: Optional[Any] = None) -> None:
        """Polls Convex for workspace lock status. If LOCKED_REFUND, terminates sub-process and aborts job cleanly."""
        from app.core import db as database
        from app.core.db import _get_service_role_client

        try:
            client = _get_service_role_client()
            ws = await database.get_workspace(client, workspace_id=workspace_id)
            if ws and (ws.get("isLocked") or ws.get("status") == "LOCKED_REFUND"):
                logger.critical(
                    f"[KILL_SWITCH] REFUND FRAUD LOCKOUT DETECTED for workspace {workspace_id}. "
                    f"Killing active sub-process for job {job_id}."
                )

                # 1. Terminate ONLY the active child sub-process (e.g. ffmpeg, model worker sub-process)
                if active_process and hasattr(active_process, "terminate"):
                    try:
                        active_process.terminate()
                        active_process.kill()
                    except Exception as e:
                        logger.error(f"[KILL_SWITCH] Subprocess kill failed: {e}")

                # 2. Raise exception to break out of job execution loop without killing worker host process
                raise JobCancelledRefundException(f"Job {job_id} terminated due to workspace refund lock.")
        except Exception as e:
            if isinstance(e, JobCancelledRefundException):
                raise
            logger.error(f"[KILL_SWITCH] Lock check failed: {e}")
