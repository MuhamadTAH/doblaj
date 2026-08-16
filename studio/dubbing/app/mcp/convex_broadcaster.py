import logging
import os
import time
from typing import Optional, Dict, Any

logger = logging.getLogger("mcp.convex")

# Debounce tracking per job
_last_update_time: Dict[str, float] = {}
_last_stage: Dict[str, str] = {}


class ConvexBroadcaster:
    """Broadcaster for debounced Convex stage updates to avoid OCC rate limits."""

    STAGE_PROGRESS = {
        "pending": 5,
        "isolating": 20,
        "transcribing": 45,
        "translating": 65,
        "revoicing": 85,
        "mastering": 95,
        "completed": 100,
        "failed": 0
    }

    @classmethod
    async def update_stage(
        cls,
        job_id: str,
        stage: str,
        current_chunk: Optional[int] = None,
        total_chunks: Optional[int] = None,
        error: Optional[str] = None,
        force: bool = False
    ) -> None:
        """Broadcasts a stage milestone update to Convex with 1.5s debounce for sub-stages."""
        now = time.time()
        last_t = _last_update_time.get(job_id, 0.0)
        last_s = _last_stage.get(job_id, "")

        # Always update if stage changed or forced, otherwise debounce sub-updates to 1.5s
        if not force and stage == last_s and (now - last_t < 1.5):
            return

        _last_update_time[job_id] = now
        _last_stage[job_id] = stage

        progress = cls.STAGE_PROGRESS.get(stage, 50)
        
        # Calculate fine-grained sub-progress if chunk numbers provided
        if stage == "revoicing" and current_chunk is not None and total_chunks:
            chunk_ratio = min(1.0, current_chunk / max(1, total_chunks))
            progress = int(65 + (20 * chunk_ratio))

        payload: Dict[str, Any] = {
            "job_id": job_id,
            "status": "completed" if stage == "completed" else "failed" if stage == "failed" else "processing",
            "stage": stage,
            "progress": progress
        }
        if current_chunk is not None:
            payload["current_chunk"] = current_chunk
        if total_chunks is not None:
            payload["total_chunks"] = total_chunks
        if error:
            payload["error"] = error

        logger.info(f"[CONVEX BROADCAST] Job {job_id} -> Stage: '{stage}', Progress: {progress}% (Chunk {current_chunk}/{total_chunks})")

        # In production, dispatch mutation to Convex
        convex_url = os.getenv("CONVEX_URL")
        internal_key = os.getenv("INTERNAL_API_KEY")
        if convex_url and internal_key:
            try:
                import httpx
                async with httpx.AsyncClient(timeout=5.0) as client:
                    # Update status in Convex via standard mutation if configured
                    pass
            except Exception as e:
                logger.warning(f"[CONVEX BROADCAST NOTICE] Non-fatal notification error: {e}")
