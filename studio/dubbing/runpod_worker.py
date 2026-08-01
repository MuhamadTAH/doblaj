import os
import asyncio
import logging
import runpod
from pathlib import Path
from app.services.video_worker_vcta import process_video_gpu_phase
from app.services import r2
from app.core import database_convex as database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("runpod_worker")

async def handler(event):
    """
    RunPod Serverless Handler.
    Receives input payload, downloads video from R2, runs the GPU phase (Stages 1-3),
    uploads intermediate zip to R2, and updates the database to gpu_finished.

    Declared async so the RunPod SDK awaits the coroutine directly
    (see runpod/serverless/modules/rp_job.py: it inspects the return
    with inspect.isawaitable and awaits if so). The previous version
    used `def handler(...): return asyncio.run(async_handler(event))`
    which crashed inside the SDK's already-running event loop.
    """
    input_data = event.get("input", {})
    job_id = input_data.get("job_id")
    workspace_id = input_data.get("workspace_id")
    category = input_data.get("category")
    entity = input_data.get("entity")
    source_video_r2_key = input_data.get("source_video_r2_key")

    if not job_id:
        return {"error": "Missing job_id"}
    if not source_video_r2_key:
        return {"error": "Missing source_video_r2_key"}

    logger.info(f"Starting RunPod Serverless job {job_id} for workspace {workspace_id}")

    # Set up local directories
    jobs_base = Path("data/jobs/sessions")
    jobs_base.mkdir(parents=True, exist_ok=True)
    
    # We will download the input video to a local path
    local_input_dir = jobs_base / "inputs"
    local_input_dir.mkdir(parents=True, exist_ok=True)
    local_input_path = local_input_dir / f"{job_id}.mp4"

    try:
        # Step 1: Download source video from R2
        logger.info(f"Downloading source video from R2 key: {source_video_r2_key}")
        await asyncio.to_thread(r2.download_file, source_video_r2_key, str(local_input_path))
        logger.info("Source video downloaded successfully")

        # Step 2: Run the GPU phase of the dubbing pipeline!
        # This will process separation, chunking, and return a zip file.
        zip_path = await process_video_gpu_phase(
            job_id=job_id,
            input_path=str(local_input_path),
            workspace_id=workspace_id,
            category=category,
            entity=entity
        )

        if not zip_path or not os.path.exists(zip_path):
            raise Exception("Failed to create intermediate zip artifact")

        # Upload the intermediate zip artifact to R2
        result_zip_r2_key = r2.dubbing_key(workspace_id, job_id, f"intermediate_{job_id}.zip")
        logger.info(f"Uploading intermediate zip to R2 under key: {result_zip_r2_key}")
        await asyncio.to_thread(r2.upload_file, result_zip_r2_key, zip_path, mime="application/zip")

        # Update Convex: GPU is finished, point at the zip on R2 so the
        # Azure CPU worker can pick it up on its next poll.
        await database.update_job_status(
            workspace_id=workspace_id,
            job_id=job_id,
            status="gpu_finished",
            progress=50,
            output_path=result_zip_r2_key,
        )
        logger.info(f"RunPod Serverless job {job_id} GPU phase completed and uploaded successfully")

        # Clean up local input file and entire session folder to free disk space
        import shutil
        if jobs_base.exists():
            shutil.rmtree(jobs_base, ignore_errors=True)

        return {"status": "success", "result_zip_r2_key": result_zip_r2_key}

    except Exception as e:
        logger.exception(f"RunPod Serverless job {job_id} failed: {e}")
        # Make sure the database is updated with the failure
        try:
            await database.update_job_status(
                workspace_id=workspace_id,
                job_id=job_id,
                status="failed",
                error=str(e),
            )
        except Exception as db_err:
            logger.error(f"Failed to update database with failure status: {db_err}")
            
        # Clean up local input file and entire session folder to free disk space
        import shutil
        if jobs_base.exists():
            shutil.rmtree(jobs_base, ignore_errors=True)
            
        return {"status": "failed", "error": str(e)}

# Start the RunPod Serverless worker
runpod.serverless.start({"handler": handler})
