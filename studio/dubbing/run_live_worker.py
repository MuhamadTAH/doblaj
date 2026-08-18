import os
import sys
import time
import json
import asyncio
import logging
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] [LOCAL-MCP-WORKER]: %(message)s"
)
logger = logging.getLogger("doblaj.local.worker")

from app.core import database_convex
from app.services import r2
from app.mcp.pipeline_engine import DubbingPipelineEngine
from app.mcp.storage import ScratchManager


AGENT_READY_FILENAME = "AGENT_TRANSCRIBE_READY"
AGENT_DONE_FILENAME = "AGENT_TRANSCRIBE_DONE"
AGENT_WAIT_TIMEOUT_SEC = 600  # 10 minutes max wait for agent


async def process_single_job(job: dict) -> None:
    """Executes the full local MCP pipeline on a job received from Railway/Convex.
    
    After stem separation, it writes a AGENT_TRANSCRIBE_READY sentinel file so 
    the Antigravity agent watcher loop can pick up the job, transcribe the Kurdish
    Sorani chunks, translate into Spoken Iraqi Arabic, and write the JSON files.
    Once AGENT_TRANSCRIBE_DONE is written by the agent, this function continues
    with voice synthesis and final delivery.
    """
    job_id = job.get("legacyId") or job.get("id") or job.get("_id")
    workspace_id = job.get("workspace_id") or job.get("workspaceId", "default")
    source_r2_key = job.get("source_video_r2_key") or job.get("sourceVideoR2Key")

    logger.info(f"[NEW JOB DETECTED] Job ID: {job_id} | Workspace: {workspace_id} | Source R2: {source_r2_key}")

    scratch_dir = ScratchManager.get_job_dir(job_id)
    local_source_path = str(scratch_dir / "source_video.mp4")

    try:
        await database_convex.update_job_status(job_id=job_id, status="separating", progress=15)

        # --- STAGE 1: Download ---
        if source_r2_key:
            logger.info(f"Downloading raw video from Cloudflare R2 ({source_r2_key})...")
            await asyncio.to_thread(r2.download_file, source_r2_key, local_source_path)
        else:
            possible_local = Path("data/uploads") / f"{job_id}.mp4"
            if possible_local.exists():
                local_source_path = str(possible_local)
            else:
                raise FileNotFoundError(f"Source video not found on R2 ({source_r2_key}) or locally")

        # --- STAGE 2: GPU Stem Separation & VAD Chunking ---
        await database_convex.update_job_status(job_id=job_id, status="separating", progress=25)
        sep_res = await DubbingPipelineEngine.separate_and_chunk(job_id, local_source_path)
        chunks_count = sep_res["chunks_count"]
        logger.info(f"  Stems separated & VAD sliced into {chunks_count} chunks")

        # --- STAGE 3: Write sentinel → Wait for Antigravity Agent ---
        # Write the "READY" file so the Antigravity watcher loop picks up this job
        ready_file = scratch_dir / AGENT_READY_FILENAME
        done_file = scratch_dir / AGENT_DONE_FILENAME
        done_file.unlink(missing_ok=True)  # clear any stale done signal

        ready_payload = {
            "job_id": job_id,
            "chunks_count": chunks_count,
            "manifest_path": sep_res["manifest_path"]
        }
        ready_file.write_text(json.dumps(ready_payload, ensure_ascii=False), encoding="utf-8")
        logger.info(f"[AGENT HANDOFF] Written sentinel file: {ready_file}")

        # Push-notify the agent watcher by appending job_id to the notify queue.
        # The agent uses a FileSystemWatcher on this file — it wakes up INSTANTLY
        # without any polling delay the moment we write here.
        notify_queue = scratch_dir.parent / "NOTIFY_QUEUE.txt"
        with open(notify_queue, "a", encoding="utf-8") as nq:
            nq.write(f"{job_id}\n")
        logger.info(f"[AGENT HANDOFF] Pushed job_id to notify queue → agent waking up now")

        # Also call the local agent_watcher /trigger endpoint so it writes
        # the PROCESS_NOW flag instantly — Antigravity's cron picks it up
        # on the very next tick (within 1 min) without any polling cost.
        try:
            import urllib.request
            trigger_data = json.dumps({"job_id": job_id}).encode("utf-8")
            req = urllib.request.Request(
                "http://127.0.0.1:8003/trigger",
                data=trigger_data,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            urllib.request.urlopen(req, timeout=2)
            logger.info(f"[AGENT HANDOFF] Push trigger sent to agent_watcher successfully")
        except Exception as e:
            logger.warning(f"[AGENT HANDOFF] Could not reach agent_watcher on port 8003: {e} (agent will still pick up via queue)")

        logger.info(f"[AGENT HANDOFF] Waiting for Antigravity to transcribe & translate {chunks_count} chunks...")

        await database_convex.update_job_status(job_id=job_id, status="transcribing", progress=45)

        # Poll until agent writes AGENT_TRANSCRIBE_DONE
        elapsed = 0
        poll_interval = 3
        while elapsed < AGENT_WAIT_TIMEOUT_SEC:
            if done_file.exists():
                logger.info(f"[AGENT HANDOFF] Agent completed transcription & translation!")
                break
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        if not done_file.exists():
            raise TimeoutError(f"Agent did not complete transcription within {AGENT_WAIT_TIMEOUT_SEC}s")

        # Clean up sentinel files
        ready_file.unlink(missing_ok=True)
        done_file.unlink(missing_ok=True)

        # --- STAGE 4: Neural Voice Cloning & Audio Mastering ---
        await database_convex.update_job_status(job_id=job_id, status="revoicing", progress=75)
        logger.info(f"[TTS] Synthesizing Iraqi Arabic cloned voice for {chunks_count} chunks...")
        master_res = await DubbingPipelineEngine.synthesize_and_master(job_id, local_source_path)
        final_mp4_path = master_res["final_video_path"]
        logger.info(f"  Master MP4 rendered: {final_mp4_path}")

        # --- STAGE 5: Upload to R2 ---
        await database_convex.update_job_status(job_id=job_id, status="mastering", progress=95)
        output_r2_key = f"dubbing/outputs/{job_id}.mp4"
        logger.info(f"Uploading final dubbed video to Cloudflare R2 ({output_r2_key})...")
        await asyncio.to_thread(r2.upload_file, output_r2_key, final_mp4_path)

        # --- STAGE 6: Mark COMPLETED in Convex ---
        trans_file = scratch_dir / "iraqi_translations_24_chunks.json"
        final_chunks_count = chunks_count
        if trans_file.exists():
            try:
                with open(trans_file, "r", encoding="utf-8") as f:
                    final_chunks_count = len(json.load(f))
            except Exception:
                pass

        await database_convex.update_job_status(
            job_id=job_id,
            status="completed",
            progress=100,
            output_path=output_r2_key,
            chunks_count=final_chunks_count
        )
        logger.info(f"Job {job_id} COMPLETED and live on doblaj.com!")

        # --- STAGE 7: Cleanup ---
        ScratchManager.cleanup_job(job_id)
        logger.info(f"Job {job_id} scratch cleaned!")

    except Exception as e:
        logger.exception(f"Error processing job {job_id}: {e}")
        try:
            await database_convex.update_job_status(
                job_id=job_id,
                status="failed",
                progress=0,
                error=str(e)
            )
        except Exception:
            pass
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
    logger.info(f"[WEBHOOK RECEIVED] Triggering job {payload.job_id}")

    job = await database_convex.get_job(job_id=payload.job_id, workspace_id=payload.workspace_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found in Convex")

    background_tasks.add_task(process_single_job, job)
    return {"status": "accepted", "job_id": payload.job_id, "message": "Job queued locally"}

def start_webhook_server():
    print("=" * 90)
    print("  [DOBLAJ LIVE LOCAL MCP WORKER] (Push Webhook Mode)")
    print("=" * 90)
    print("Listening on http://127.0.0.1:8002 for incoming Webhooks from Railway...")
    print("Permanent tunnel endpoint: https://worker.doblaj.com\n")
    uvicorn.run(app, host="127.0.0.1", port=8002, log_level="info")

if __name__ == "__main__":
    start_webhook_server()
