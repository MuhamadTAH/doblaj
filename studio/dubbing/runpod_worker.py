import os
import asyncio
import logging
import runpod
from pathlib import Path
from app.services.node2_separation import process_node2_separation
from app.services import r2
from app.core import database_convex as database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("runpod_worker")

async def handler(event):
    """
    RunPod Serverless GPU Worker Handler.
    Receives input payload from FastAPI API Gateway, executes heavy GPU tasks (Demucs separation,
    Silero VAD segmentation, 44.1kHz slicing), uploads stems & chunks to R2, and updates Convex state.
    """
    input_data = event.get("input", {})
    job_id = input_data.get("job_id")
    workspace_id = input_data.get("workspace_id", "default")
    source_video_r2_key = input_data.get("source_video_r2_key")

    if not job_id:
        return {"error": "Missing job_id"}
    if not source_video_r2_key:
        return {"error": "Missing source_video_r2_key"}

    logger.info(f"[RUNPOD-GPU] Starting isolated GPU worker execution for job {job_id}")

    try:
        # Execute Node 2 separation on dedicated GPU
        sep_res = await process_node2_separation(
            job_id=job_id,
            workspace_id=workspace_id,
            source_r2_key=source_video_r2_key,
        )
        logger.info(f"[RUNPOD-GPU] Node 2 separation complete for job {job_id}: {sep_res.get('chunks_count')} chunks created")
        return {"status": "success", "data": sep_res}

    except Exception as e:
        logger.exception(f"[RUNPOD-GPU] Job {job_id} failed on RunPod GPU worker: {e}")
        try:
            c = database._get_client()
            await asyncio.to_thread(
                c.mutation,
                "dubbingJobs:updateStatusInternal",
                {
                    "__internalApiKey": os.getenv("INTERNAL_API_KEY", ""),
                    "jobId": job_id,
                    "status": "failed",
                    "error": f"GPU Worker Error: {str(e)}",
                }
            )
        except Exception as db_err:
            logger.error(f"Failed to update database with failure status: {db_err}")

        return {"status": "failed", "error": str(e)}

# Start the RunPod Serverless worker loop
runpod.serverless.start({"handler": handler})
