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
AGENT_WAIT_TIMEOUT_SEC = 3600  # 1 hour max wait for agent session


async def wait_for_agent_transcription_and_translation(job_id: str, scratch_dir: Path, timeout_sec: int = 3600) -> bool:
    ready_file = scratch_dir / AGENT_READY_FILENAME
    done_file = scratch_dir / AGENT_DONE_FILENAME
    
    # 1. Write AGENT_TRANSCRIBE_READY
    manifest_path = scratch_dir / "mp4_chunks_manifest.json"
    ready_data = {
        "job_id": job_id,
        "full_video_mp4": str(scratch_dir / "source_video.mp4"),
        "full_vocals_wav": str(scratch_dir / "vocals_stem.wav"),
        "manifest_path": str(manifest_path),
        "chunks_dir": str(scratch_dir / "chunks"),
        "timestamp": time.time()
    }
    with open(ready_file, "w", encoding="utf-8") as f:
        json.dump(ready_data, f, indent=2)
        
    # 2. Append to NOTIFY_QUEUE.txt to trigger FileSystemWatcher
    notify_file = Path("tmp/doblaj_scratch/NOTIFY_QUEUE.txt")
    notify_file.parent.mkdir(parents=True, exist_ok=True)
    with open(notify_file, "a", encoding="utf-8") as f:
        f.write(f"JOB_READY:{job_id} at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        
    logger.info(f"✨ [AGENT HANDOFF] Sentinel written: {ready_file}. Notified Antigravity subagent session. Waiting for AGENT_TRANSCRIBE_DONE...")
    
    # 3. Wait for AGENT_TRANSCRIBE_DONE
    start_t = time.time()
    while time.time() - start_t < timeout_sec:
        if done_file.exists():
            logger.info(f"✅ [AGENT HANDOFF] Subagents completed transcription & translation for {job_id} in {time.time() - start_t:.1f}s!")
            return True
        await asyncio.sleep(2.0)
        
    logger.error(f"❌ [AGENT HANDOFF] Timed out after {timeout_sec}s waiting for Antigravity subagents. Aborting without bad fallbacks.")
    return False


async def process_single_job(job: dict) -> None:
    """Executes the full local MCP pipeline on a job received from Railway/Convex."""
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

        # --- STAGE 3 & 4: Antigravity Subagents Handoff (Kurdish STT & Iraqi Translation) ---
        await database_convex.update_job_status(job_id=job_id, status="transcribing", progress=45)
        subagent_done = await wait_for_agent_transcription_and_translation(job_id, scratch_dir, timeout_sec=AGENT_WAIT_TIMEOUT_SEC)
        
        if not subagent_done:
            logger.error(f"[WORKER ERROR] Job {job_id} aborted: Subagents did not write AGENT_TRANSCRIBE_DONE within {AGENT_WAIT_TIMEOUT_SEC}s.")
            await database_convex.update_job_status(job_id=job_id, status="failed", progress=0)
            return

        await database_convex.update_job_status(job_id=job_id, status="translating", progress=65)

        # --- STAGE 5: Neural Voice Cloning & Audio Mastering ---
        await database_convex.update_job_status(job_id=job_id, status="revoicing", progress=80)
        logger.info(f"[TTS] Synthesizing Iraqi Arabic cloned voice with Fish Audio for {chunks_count} chunks...")
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
_active_jobs = set()

class WebhookPayload(BaseModel):
    job_id: str
    workspace_id: str = ""

async def _run_job_wrapper(job: dict, jid: str):
    try:
        await process_single_job(job)
    finally:
        _active_jobs.discard(jid)

async def convex_polling_loop():
    """Continuously poll Convex for pending jobs so processing starts automatically."""
    logger.info("[POLLER] Convex pending jobs autonomous poller started.")
    while True:
        try:
            await asyncio.sleep(4.0)
            c = database_convex._get_client()
            pending_jobs = c.query('dubbingJobs:listByStatusInternal', database_convex._internal_args({'status': 'pending', 'limit': 5})) or []
            for job in pending_jobs:
                jid = job.get("legacyId") or job.get("id") or job.get("_id")
                if jid and jid not in _active_jobs:
                    _active_jobs.add(jid)
                    logger.info(f"[AUTONOMOUS WORKER] Detected pending job {jid} in Convex! Starting processing...")
                    asyncio.create_task(_run_job_wrapper(job, jid))
        except Exception as e:
            logger.debug(f"[POLLER] Notice: {e}")

@app.on_event("startup")
async def on_startup():
    asyncio.create_task(convex_polling_loop())
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if tg_token:
        from app.services.telegram_dubbing_bot import start_telegram_bot
        asyncio.create_task(start_telegram_bot(tg_token))

@app.post("/webhook/run_job")
async def handle_webhook_run_job(payload: WebhookPayload, background_tasks: BackgroundTasks):
    logger.info(f"[WEBHOOK RECEIVED] Triggering job {payload.job_id}")

    job = await database_convex.get_job(job_id=payload.job_id, workspace_id="")
    if not job:
        raise HTTPException(status_code=404, detail="Job not found in Convex")

    jid = payload.job_id
    if jid not in _active_jobs:
        _active_jobs.add(jid)
        background_tasks.add_task(_run_job_wrapper, job, jid)
    return {"status": "accepted", "job_id": payload.job_id, "message": "Job queued locally"}

def start_webhook_server():
    print("=" * 90)
    print("  [DOBLAJ LIVE LOCAL MCP WORKER] (Autonomous Polling + Push Webhook Mode)")
    print("=" * 90)
    print("Listening on http://127.0.0.1:8002 & polling Convex for pending jobs automatically...")
    print("Permanent tunnel endpoint: https://worker.doblaj.com\n")
    uvicorn.run(app, host="127.0.0.1", port=8002, log_level="info")

if __name__ == "__main__":
    start_webhook_server()
