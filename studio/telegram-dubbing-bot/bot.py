#!/usr/bin/env python3
"""
Pird AI Video Dubbing Telegram Bot
Architecture: Aiogram 3.x (Polling local API server) + aiohttp Webhook (Internal callbacks) + SQLite (State)
"""

import asyncio
import io
import os
import signal
import sys
import time
import logging
import traceback
from typing import Dict, Any, Optional

import aiosqlite
import httpx
from aiohttp import web
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.telegram import TelegramAPIServer
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.types import Message, FSInputFile
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from pythonjsonlogger import jsonlogger

# =====================================================================
# 1. STRUCTURED LOGGING
# =====================================================================
logger = logging.getLogger("telegram_dubbing_bot")
logger.setLevel(logging.INFO)
logHandler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter(
    "%(asctime)s %(levelname)s %(name)s %(message)s"
)
logHandler.setFormatter(formatter)
logger.addHandler(logHandler)

# =====================================================================
# 2. CONFIGURATION & SECRETS
# =====================================================================
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
LOCAL_API_SERVER_URL = os.getenv("LOCAL_API_SERVER_URL", "http://telegram-bot-api:8081")
DUBBING_BACKEND_URL = os.getenv("DUBBING_BACKEND_URL", "http://backend:8000")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "pird_internal_dubbing_key_2026")

DB_PATH = "/app/state/jobs.db"
OUTPUTS_DIR = "/var/lib/telegram-bot-api/pird_outputs"

if not BOT_TOKEN:
    raise ValueError("CRITICAL: TELEGRAM_BOT_TOKEN is missing.")

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
os.makedirs(OUTPUTS_DIR, exist_ok=True)

# Globals for shutdown sequence
is_shutting_down = False
db_connection: Optional[aiosqlite.Connection] = None
job_queue: asyncio.Queue = asyncio.Queue()
bot_instance: Optional[Bot] = None
dispatcher_instance: Optional[Dispatcher] = None
webhook_app_runner: Optional[web.AppRunner] = None

# =====================================================================
# 3. SQLITE DATABASE STATE MACHINE
# =====================================================================
# States: PENDING -> READY_FOR_DOWNLOAD -> DOWNLOADING -> SENDING -> DELIVERED

async def init_db():
    global db_connection
    db_connection = await aiosqlite.connect(DB_PATH, timeout=10.0)
    await db_connection.execute('PRAGMA journal_mode=WAL;')
    await db_connection.execute('''
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            chat_id INTEGER,
            status TEXT,
            input_file_path TEXT,
            target_lang TEXT,
            voice TEXT,
            created_at INTEGER
        )
    ''')
    await db_connection.commit()
    logger.info({"service": "database", "message": "SQLite initialized with WAL."})

async def update_job_status(job_id: str, status: str):
    if db_connection:
        await db_connection.execute("UPDATE jobs SET status = ? WHERE job_id = ?", (status, job_id))
        await db_connection.commit()

async def get_job(job_id: str):
    if db_connection:
        async with db_connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "job_id": row[0],
                    "chat_id": row[1],
                    "status": row[2],
                    "input_file_path": row[3],
                    "target_lang": row[4],
                    "voice": row[5]
                }
    return None

# =====================================================================
# 4. BACKGROUND QUEUE WORKER
# =====================================================================
async def process_job_queue():
    while not is_shutting_down or not job_queue.empty():
        try:
            job_id = await job_queue.get()
        except asyncio.CancelledError:
            break
            
        try:
            job = await get_job(job_id)
            if not job:
                continue
                
            chat_id = job["chat_id"]
            
            # 1. DOWNLOAD PHASE
            await update_job_status(job_id, "DOWNLOADING")
            result_url = f"{DUBBING_BACKEND_URL.rstrip('/')}/video/internal/jobs/{job_id}/download"
            local_out_path = os.path.join(OUTPUTS_DIR, f"{job_id}_dubbed.mp4")
            
            # Check if file is already there (from a SENDING crash)
            if not os.path.exists(local_out_path):
                logger.info({"service": "worker", "message": f"Downloading dubbed video for {job_id}"})
                headers = {"x-internal-key": INTERNAL_API_KEY} if INTERNAL_API_KEY else {}
                async with httpx.AsyncClient(timeout=1800.0) as client:
                    async with client.stream('GET', result_url, headers=headers) as resp:
                        if resp.status_code == 200:
                            with open(local_out_path, 'wb') as f:
                                async for chunk in resp.aiter_bytes():
                                    f.write(chunk)
                        else:
                            raise Exception(f"Failed to download video: HTTP {resp.status_code}")
                            
            # 2. SENDING PHASE
            await update_job_status(job_id, "SENDING")
            logger.info({"service": "worker", "message": f"Sending dubbed video to user {chat_id}"})
            if bot_instance:
                video = FSInputFile(local_out_path)
                await bot_instance.send_message(
                    chat_id=chat_id,
                    text="✅ **Dubbing Complete! / تمت الدبلجة بنجاح! / دۆبلاژکردن تەواو بوو!**\nHere is your dubbed video:"
                )
                await bot_instance.send_video(
                    chat_id=chat_id, 
                    video=video, 
                    caption=f"🗣️ Lang: {job['target_lang'].upper()} | 🎙️ Voice: {job['voice'].title()}",
                    request_timeout=1800 # 30 min timeout for massive uploads
                )
                
            # 3. DELIVERED PHASE
            await update_job_status(job_id, "DELIVERED")
            
            # Hygiene
            try:
                os.remove(local_out_path)
                logger.info({"service": "worker", "message": f"Deleted output file {local_out_path}"})
            except OSError as e:
                logger.warning({"service": "worker", "message": f"Output file locked, deferring to sweeper: {e}"})

        except Exception as e:
            logger.error({"service": "worker", "message": f"Error processing job {job_id}", "error": str(e), "traceback": traceback.format_exc()})
            if bot_instance and 'chat_id' in locals():
                try:
                    await bot_instance.send_message(
                        chat_id=chat_id,
                        text="⚠️ **Error during processing / خطأ في المعالجة / هەڵەیەک روویدا**"
                    )
                except:
                    pass
        finally:
            job_queue.task_done()
            
# =====================================================================
# 5. STARTUP RECONCILIATION
# =====================================================================
async def startup_reconciliation():
    logger.info({"service": "startup", "message": "Running startup reconciliation for lost jobs..."})
    if not db_connection:
        return
        
    async with db_connection.execute("SELECT job_id, status FROM jobs WHERE status IN ('PENDING', 'DOWNLOADING', 'SENDING')") as cursor:
        rows = await cursor.fetchall()
        
    for row in rows:
        job_id, status = row[0], row[1]
        logger.info({"service": "startup", "message": f"Reconciling job {job_id} (State: {status})"})
        
        if status == 'SENDING':
            # Job crashed during Telegram upload, try to resume if file exists
            await update_job_status(job_id, "READY_FOR_DOWNLOAD")
            job_queue.put_nowait(job_id)
        elif status == 'DOWNLOADING':
            # Job crashed during download, restart download
            await update_job_status(job_id, "READY_FOR_DOWNLOAD")
            job_queue.put_nowait(job_id)
        elif status == 'PENDING':
            # Query backend to see if it's done
            try:
                status_url = f"{DUBBING_BACKEND_URL.rstrip('/')}/video/internal/jobs/{job_id}/status"
                headers = {"x-internal-key": INTERNAL_API_KEY} if INTERNAL_API_KEY else {}
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(status_url, headers=headers)
                    if resp.status_code == 200:
                        sdata = resp.json()
                        if sdata.get("status") == "completed":
                            logger.info({"service": "startup", "message": f"Job {job_id} is completed on backend, queueing."})
                            await update_job_status(job_id, "READY_FOR_DOWNLOAD")
                            job_queue.put_nowait(job_id)
            except Exception as e:
                logger.warning({"service": "startup", "message": f"Failed to check pending job {job_id} status: {e}"})

# =====================================================================
# 6. INTERNAL WEBHOOK RECEIVER (FastAPI to Bot)
# =====================================================================
async def internal_webhook(request: web.Request):
    try:
        data = await request.json()
        job_id = data.get("job_id")
        status = data.get("status")
        
        if job_id and status == "completed":
            logger.info({"service": "webhook", "message": f"Backend signaled completion for {job_id}"})
            await update_job_status(job_id, "READY_FOR_DOWNLOAD")
            job_queue.put_nowait(job_id)
            return web.Response(status=202, text="Accepted")
        return web.Response(status=400, text="Bad Request")
    except Exception as e:
        logger.error({"service": "webhook", "message": f"Webhook error: {e}"})
        return web.Response(status=500, text="Internal Error")

# =====================================================================
# 7. AIOGRAM ROUTER & UPLOAD LOGIC
# =====================================================================
class DubbingConfig(StatesGroup):
    waiting_for_video = State()

router = Router()

@router.message(CommandStart())
async def handle_start(message: Message, state: FSMContext):
    await state.clear()
    
    args = message.text.split()
    if len(args) > 1:
        nonce = args[1]
        logger.info({"service": "auth", "message": f"Received link nonce {nonce}"})
        headers = {"x-internal-key": INTERNAL_API_KEY} if INTERNAL_API_KEY else {}
        verify_url = f"{DUBBING_BACKEND_URL.rstrip('/')}/api/telegram/link-verify"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(verify_url, json={"nonce": nonce, "telegram_chat_id": str(message.chat.id)}, headers=headers)
                if resp.status_code == 200:
                    await message.answer("✅ Your Telegram account has been successfully linked to your Doblaj workspace!\nYou can now upload videos here to dub them.")
                elif resp.status_code == 409:
                    await message.answer("⚠️ This workspace is already linked to another Telegram account.")
                else:
                    await message.answer("⚠️ Invalid or expired link token. Please generate a new one from the dashboard.")
        except Exception as e:
            logger.error({"service": "auth", "message": f"Error linking account: {e}"})
            await message.answer("⚠️ Error communicating with the server. Please try again later.")
        return

    await state.set_state(DubbingConfig.waiting_for_video)
    
    welcome_text = (
        "👋 Welcome to the AI Video Dubbing Bot!\n"
        "Please upload a video file (MP4, MOV, MKV, WEBM, AVI, max 2000 MB) to start translating and dubbing.\n\n"
        "🇮🇶 مرحباً بك في بوت الدبلجة الفورية بالفيديو!\n"
        "يرجى رفع مقطع فيديو بحد أقصى 2000 MB للبدء في الترجمة والدبلجة.\n\n"
        "☀️ بەخێربێن بۆ بۆتی دۆبلاژکردنی ڤیدیۆ بە ژیری دەستکرد!\n"
        "تکایە ڤیدیۆیەک بباربکە بۆ دەستپێکردنی وەرگێڕان و دۆبلاژکردن."
    )
    await message.answer(welcome_text)

@router.message(DubbingConfig.waiting_for_video, F.video | F.document)
async def handle_video_upload(message: Message, state: FSMContext):
    if is_shutting_down:
        await message.reply("⚠️ Service is shutting down for updates. Please try again later.")
        return
        
    video_obj = message.video or message.document
    max_bytes = 2000 * 1024 * 1024
    
    if not video_obj.file_size or video_obj.file_size > max_bytes:
        await message.reply("⚠️ File too large (max 2000 MB).")
        return

    duration_seconds = getattr(video_obj, 'duration', 0)
    if duration_seconds <= 0:
        # Fallback for documents: assume 1 minute per 15MB
        duration_seconds = int((video_obj.file_size / (15 * 1024 * 1024)) * 60)
        if duration_seconds <= 0:
            duration_seconds = 60

    await state.clear()
    await message.answer("⏳ Checking account balance...")
    
    # Pre-flight reservation
    headers = {"x-internal-key": INTERNAL_API_KEY} if INTERNAL_API_KEY else {}
    reserve_url = f"{DUBBING_BACKEND_URL.rstrip('/')}/api/telegram/jobs/reserve"
    reservation_id = None
    minutes_reserved = 0
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(reserve_url, json={
                "telegram_chat_id": str(message.chat.id),
                "video_duration_seconds": duration_seconds
            }, headers=headers)
            
            if resp.status_code == 404:
                await message.answer("⚠️ Your Telegram account is not linked to a workspace. Please link it from the Doblaj dashboard first.")
                return
            elif resp.status_code == 402:
                err_detail = resp.json().get("detail", "Insufficient minutes.")
                await message.answer(f"⚠️ {err_detail}\nPlease top up your balance on the dashboard.")
                return
            elif resp.status_code != 200:
                await message.answer("⚠️ Error verifying account balance. Please try again later.")
                return
                
            data = resp.json()
            reservation_id = data.get("reservation_id")
            minutes_reserved = data.get("minutes_reserved")
            
    except Exception as e:
        logger.error({"service": "upload", "message": f"Error reserving minutes: {e}"})
        await message.answer("⚠️ Error verifying account balance. Please try again later.")
        return

    await message.answer("✅ Balance verified. Processing... submitting to dubbing pipeline.")
    
    # 1. Submit to Backend
    try:
        file_info = await bot_instance.get_file(video_obj.file_id)
        local_input_path = file_info.file_path
        
        # Check if file exists locally on the shared volume
        if not os.path.exists(local_input_path):
            raise Exception(f"Local file not found at {local_input_path}")
            
        logger.info({"service": "upload", "message": "Streaming upload to backend..."})
        
        # Open file to stream it directly via httpx, preventing OOM
        f = open(local_input_path, 'rb')
        
        headers = {"x-internal-key": INTERNAL_API_KEY} if INTERNAL_API_KEY else {}
        form_data = {
            "chat_id": str(message.chat.id),
            "source": "telegram",
            "webhook_url": "http://python-bot:8000/callback"
        }
        files = {"file": (os.path.basename(local_input_path), f, "video/mp4")}
        
        async with httpx.AsyncClient(timeout=1800.0) as client:
            backend_jobs_url = f"{DUBBING_BACKEND_URL.rstrip('/')}/video/internal/jobs"
            resp = await client.post(backend_jobs_url, data=form_data, files=files, headers=headers)
            f.close()
            
            if resp.status_code not in (200, 201, 202):
                raise RuntimeError(f"Backend rejected job: {resp.text}")
                
            data = resp.json()
            job_id = data.get("id")
            
            # Insert to DB
            if db_connection:
                await db_connection.execute('''
                    INSERT INTO jobs (job_id, chat_id, status, input_file_path, target_lang, voice, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (job_id, message.chat.id, "PENDING", local_input_path, "ar_iq", "auto_clone", int(time.time())))
                await db_connection.commit()
                
            # Input Hemorrhage Fix: Explicitly delete the input immediately
            try:
                os.remove(local_input_path)
                logger.info({"service": "upload", "message": f"Successfully deleted input file {local_input_path}"})
            except OSError as err:
                logger.warning({"service": "upload", "message": f"Input file locked, deferring to sweeper: {err}"})

    except Exception as e:
        logger.error({"service": "upload", "message": "Error submitting job", "error": str(e)})
        await message.answer("⚠️ Error submitting your video. Please try again.")
        # Refund minutes if reserved
        if reservation_id and minutes_reserved > 0:
            try:
                refund_url = f"{DUBBING_BACKEND_URL.rstrip('/')}/api/telegram/jobs/refund"
                async with httpx.AsyncClient() as client:
                    await client.post(refund_url, json={
                        "reservation_id": reservation_id,
                        "telegram_chat_id": str(message.chat.id),
                        "minutes_to_refund": minutes_reserved
                    }, headers=headers)
                logger.info({"service": "upload", "message": f"Refunded {minutes_reserved} minutes for failed job."})
            except Exception as refund_e:
                logger.error({"service": "upload", "message": f"Failed to refund minutes: {refund_e}"})

# =====================================================================
# 8. SHUTDOWN SEQUENCE
# =====================================================================
async def graceful_shutdown(sig):
    global is_shutting_down
    logger.info({"service": "devops", "message": f"Received signal {sig.name}. Starting Graceful Shutdown..."})
    is_shutting_down = True
    
    # 1. Stop webhook server
    if webhook_app_runner:
        logger.info({"service": "devops", "message": "Stopping webhook receiver (rejecting new incoming webhooks)..."})
        await webhook_app_runner.cleanup()
        
    # 2. Stop aiogram polling
    if dispatcher_instance and bot_instance:
        logger.info({"service": "devops", "message": "Stopping aiogram polling (rejecting new user messages)..."})
        await dispatcher_instance.stop_polling()
        
    # 3. Drain asyncio.Queue
    logger.info({"service": "devops", "message": "Waiting for active downloads and Telegram uploads to finish..."})
    await job_queue.join()
    
    # 4. Close DB
    if db_connection:
        logger.info({"service": "devops", "message": "Closing SQLite connection safely..."})
        await db_connection.close()
        
    logger.info({"service": "devops", "message": "Graceful Shutdown complete. Exiting."})
    sys.exit(0)

# =====================================================================
# 9. MAIN LIFECYCLE
# =====================================================================
async def main():
    global bot_instance, dispatcher_instance, webhook_app_runner
    
    # Setup Signal Handlers
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(graceful_shutdown(s)))

    # Init SQLite
    await init_db()
    
    # Startup Reconciliation
    await startup_reconciliation()
    
    # Start Queue Worker
    worker_task = asyncio.create_task(process_job_queue())

    # Start Aiohttp Webhook Server
    app = web.Application()
    app.router.add_post("/callback", internal_webhook)
    webhook_app_runner = web.AppRunner(app)
    await webhook_app_runner.setup()
    site = web.TCPSite(webhook_app_runner, '0.0.0.0', 8000)
    await site.start()
    logger.info({"service": "devops", "message": "Internal Webhook Receiver started on 0.0.0.0:8000/callback"})

    # Start Aiogram Polling
    api_server = TelegramAPIServer.from_base(LOCAL_API_SERVER_URL, is_local=True)
    session = AiohttpSession(api=api_server, timeout=1800.0) # 30 mins
    bot_instance = Bot(token=BOT_TOKEN, session=session)
    dispatcher_instance = Dispatcher(storage=MemoryStorage())
    dispatcher_instance.include_router(router)
    
    logger.info({"service": "devops", "message": f"Starting Telegram Polling via {LOCAL_API_SERVER_URL}..."})
    
    try:
        await bot_instance.delete_webhook(drop_pending_updates=True) # Ensure we aren't using webhooks for Telegram
        await dispatcher_instance.start_polling(bot_instance)
    except asyncio.CancelledError:
        pass
    finally:
        await bot_instance.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
