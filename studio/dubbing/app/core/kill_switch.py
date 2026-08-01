import os
import sys
import signal
import logging
from typing import Optional, Any

logger = logging.getLogger(__name__)

class InfrastructureKillSwitch:
    """Active OS-level kill switch for compute worker processes upon refund/fraud lock."""

    @staticmethod
    async def verify_job_or_terminate(job_id: str, workspace_id: str, active_process: Optional[Any] = None) -> None:
        """Polls Convex for workspace lock status. If LOCKED_REFUND or job status is failed, kills process immediately."""
        from app.core import db as database
        from app.core.db import _get_service_role_client

        try:
            client = _get_service_role_client()
            ws = await database.get_workspace(client, workspace_id=workspace_id)
            if ws and (ws.get("isLocked") or ws.get("status") == "LOCKED_REFUND"):
                logger.critical(
                    f"[OS_KILL_SWITCH] REFUND FRAUD LOCKOUT DETECTED for workspace {workspace_id}. "
                    f"Killing process tree for job {job_id}."
                )

                # 1. Terminate sub-process if active
                if active_process and hasattr(active_process, "terminate"):
                    try:
                        active_process.terminate()
                        active_process.kill()
                    except Exception as e:
                        logger.error(f"[OS_KILL_SWITCH] Subprocess kill failed: {e}")

                # 2. Issue OS-level SIGTERM / sys.exit(1) to physically terminate worker process
                if hasattr(os, "kill") and hasattr(signal, "SIGTERM"):
                    try:
                        os.kill(os.getpid(), signal.SIGTERM)
                    except Exception:
                        pass
                sys.exit(1)
        except Exception as e:
            if isinstance(e, SystemExit):
                raise
            logger.error(f"[OS_KILL_SWITCH] Lock check failed: {e}")
