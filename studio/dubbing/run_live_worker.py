import os
import sys
import time
import json
import asyncio
import logging
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] [LOCAL-MCP-WORKER]: %(message)s"
)
logger = logging.getLogger("doblaj.local.worker")

from app.core import database_convex
from app.services import r2
from app.mcp.pipeline_engine import DubbingPipelineEngine
from app.mcp.storage import ScratchManager
from app.mcp.convex_broadcaster import ConvexBroadcaster


async def process_single_job(job: dict) -> None:
    """Executes the full local MCP pipeline on a job received from Railway/Convex."""
    job_id = job.get("legacyId") or job.get("id") or job.get("_id")
    workspace_id = job.get("workspace_id") or job.get("workspaceId", "default")
    source_r2_key = job.get("source_video_r2_key") or job.get("sourceVideoR2Key")
    
    logger.info(f"🚀 [NEW JOB DETECTED] Job ID: {job_id} | Workspace: {workspace_id} | Source R2: {source_r2_key}")
    
    scratch_dir = ScratchManager.get_job_dir(job_id)
    local_source_path = str(scratch_dir / "source_video.mp4")
    
    try:
        # Broadcast initial processing stage
        await database_convex.update_job_status(job_id=job_id, status="separating", progress=15)

        # 1. Download source video from Cloudflare R2
        if source_r2_key:
            logger.info(f"📥 Downloading raw video from Cloudflare R2 ({source_r2_key})...")
            await asyncio.to_thread(r2.download_file, source_r2_key, local_source_path)
        else:
            # Check local uploads if not on R2
            possible_local = Path("data/uploads") / f"{job_id}.mp4"
            if possible_local.exists():
                local_source_path = str(possible_local)
            else:
                raise FileNotFoundError(f"Source video not found on R2 ({source_r2_key}) or locally")
                
        # 2. Run the 7-Stage Local MCP Dubbing Engine
        logger.info(f"⚙️ Running 7-Stage Local MCP Dubbing Pipeline for {job_id}...")
        
        # Step A: Stem Separation & Chunking
        await database_convex.update_job_status(job_id=job_id, status="separating", progress=25)
        sep_res = await DubbingPipelineEngine.separate_and_chunk(job_id, local_source_path)
        logger.info(f"  ✅ Stems separated & VAD sliced into {sep_res['chunks_count']} chunks")
        
        # Step B: Dual-Pass Kurdish STT
        await database_convex.update_job_status(job_id=job_id, status="transcribing", progress=45)
        stt_res = await DubbingPipelineEngine.transcribe_kurdish(job_id)
        logger.info(f"  ✅ Dual-Pass STT complete: {stt_res['transcriptions_count']} Kurdish transcriptions")
        
        # Step C: Spoken Iraqi Localization & Calibration
        await database_convex.update_job_status(job_id=job_id, status="translating", progress=65)
        calib_res = await DubbingPipelineEngine.translate_and_calibrate(job_id, retry_count=0)
        if calib_res.get("status") == "SPEED_BOUNDARY_VIOLATION":
            logger.info("  ⚡ Speed boundary triggered -> Auto-calibrating word targets...")
            calib_res = await DubbingPipelineEngine.translate_and_calibrate(job_id, retry_count=1)
        logger.info(f"  ✅ Iraqi localization & lipsync calibrated successfully")
        
        # Step D: Single Master Voice Anchor Synthesis + Mastering + Quran Outro Crossfade
        await database_convex.update_job_status(job_id=job_id, status="revoicing", progress=85)
        master_res = await DubbingPipelineEngine.synthesize_and_master(job_id, local_source_path)
        final_mp4_path = master_res["final_video_path"]
        logger.info(f"  ✅ Master MP4 rendered: {final_mp4_path}")
        
        # 3. Upload Mastered Video back to Cloudflare R2
        await database_convex.update_job_status(job_id=job_id, status="mastering", progress=95)
        output_r2_key = f"dubbing/outputs/{job_id}.mp4"
        logger.info(f"📤 Uploading final dubbed video to Cloudflare R2 ({output_r2_key})...")
        await asyncio.to_thread(r2.upload_file, output_r2_key, final_mp4_path)
        
        # 4. Update Convex DB Status to COMPLETED
        await database_convex.update_job_status(
            job_id=job_id,
            status="completed",
            progress=100,
            output_path=output_r2_key
        )
        logger.info(f"🎉 Convex updated to COMPLETED! User on doblaj.com can now watch the video.")
                
        # 5. Clean up local scratch disk
        ScratchManager.cleanup_job(job_id)
        logger.info(f"✨ Job {job_id} completely finished & local scratch cleaned!\n")
        
    except Exception as e:
        logger.exception(f"❌ Error processing job {job_id}: {e}")
        try:
            await database_convex.update_job_status(
                job_id=job_id,
                status="failed",
                progress=0,
                error=str(e)
            )
        except Exception:
            pass
        # Clean up on error
        ScratchManager.cleanup_job(job_id)


from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel
import uvicorn

app = FastAPI(title="Local MCP Webhook Worker")

class WebhookPayload(BaseModel):
    job_id: str
    workspace_id: str = "default"

@app.post("/webhook/run_job")
async def handle_webhook_run_job(payload: WebhookPayload, background_tasks: BackgroundTasks):
    logger.info(f"🔔 [WEBHOOK RECEIVED] Triggering job {payload.job_id}")
    
    # Fetch the full job dict from Convex using the job_id
    job = await database_convex.get_job(job_id=payload.job_id, workspace_id=payload.workspace_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found in Convex")
        
    # Run the 7-stage engine in the background
    background_tasks.add_task(process_single_job, job)
    return {"status": "accepted", "job_id": payload.job_id, "message": "Job queued locally"}

def start_webhook_server():
    print("="*90)
    print("  🚀 DOBLAJ LIVE LOCAL MCP WORKER (Push Webhook Mode)")
    print("="*90)
    print("Listening on http://127.0.0.1:8002 for incoming Webhooks from Railway...")
    print("Run this command in a NEW terminal to connect to Railway:")
    print("    cloudflared tunnel --url http://127.0.0.1:8002\n")
    uvicorn.run(app, host="127.0.0.1", port=8002, log_level="warning")

if __name__ == "__main__":
    start_webhook_server()
