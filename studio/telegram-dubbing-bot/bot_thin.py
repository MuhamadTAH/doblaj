import os
import asyncio
import logging
from aiogram import Bot, Dispatcher, F, types
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.filters import CommandStart
import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Config
BOT_TOKEN = os.getenv("BOT_TOKEN")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY")
BOT_SERVICE_USER_ID = os.getenv("BOT_SERVICE_USER_ID")
BOT_SERVICE_WORKSPACE_ID = os.getenv("BOT_SERVICE_WORKSPACE_ID")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
TELEGRAM_API_URL = os.getenv("TELEGRAM_API_URL", "http://127.0.0.1:8081")

# The path mapping from docker container to host
TELEGRAM_DATA_HOST_DIR = os.getenv("TELEGRAM_DATA_HOST_DIR", os.path.join(os.path.dirname(__file__), "telegram-data"))
TELEGRAM_DATA_CONTAINER_DIR = "/var/lib/telegram-bot-api"

if not all([BOT_TOKEN, INTERNAL_API_KEY]):
    raise ValueError("Missing BOT_TOKEN or INTERNAL_API_KEY")

session = AiohttpSession(
    api=TelegramAPIServer.from_base(TELEGRAM_API_URL, is_local=True)
)
bot = Bot(token=BOT_TOKEN, session=session)
dp = Dispatcher()

async def post_video_to_backend(local_path: str, message: types.Message):
    url = f"{BACKEND_URL}/api/video/jobs"
    headers = {
        "x-internal-key": INTERNAL_API_KEY
    }
    
    # Send file to backend
    async with httpx.AsyncClient(timeout=None) as client:
        with open(local_path, "rb") as f:
            files = {"file": (os.path.basename(local_path), f, "video/mp4")}
            response = await client.post(url, headers=headers, files=files)
            
            if response.status_code != 200:
                logger.error(f"Failed to submit job: {response.text}")
                await message.reply(f"Failed to start dubbing job: {response.text}")
                return None
            
            return response.json()

async def poll_job_status(job_id: str, status_msg: types.Message, original_message: types.Message):
    url = f"{BACKEND_URL}/api/internal/jobs/{job_id}/status"
    headers = {
        "x-internal-key": INTERNAL_API_KEY
    }
    
    await status_msg.edit_text("Dubbing job started! Checking status...")
    
    async with httpx.AsyncClient() as client:
        while True:
            response = await client.get(url, headers=headers)
            if response.status_code != 200:
                logger.error(f"Error checking status: {response.text}")
                await status_msg.edit_text("Error checking status. Please try again later.")
                break
                
            data = response.json()
            status = data.get("status")
            progress = data.get("progress", 0)
            
            if status in ("completed", "done"):
                download_url = f"{BACKEND_URL}/api/internal/jobs/{job_id}/download"
                
                # Check if it redirects to R2 or serves locally
                resp = await client.get(download_url, headers=headers, follow_redirects=False)
                if resp.status_code in (301, 302, 303, 307, 308):
                    final_url = resp.headers["Location"]
                    await status_msg.edit_text(f"✅ Dubbing completed!\nDownload your video here: {final_url}")
                else:
                    if resp.status_code == 200:
                        await status_msg.edit_text("✅ Dubbing completed! Uploading back to Telegram...")
                        
                        import tempfile
                        tmp_path = os.path.join(TELEGRAM_DATA_HOST_DIR, f"out_{job_id}.mp4")
                        os.makedirs(TELEGRAM_DATA_HOST_DIR, exist_ok=True)
                        with open(tmp_path, "wb") as out_f:
                            async with client.stream("GET", download_url, headers=headers) as stream:
                                async for chunk in stream.aiter_bytes():
                                    out_f.write(chunk)
                        
                        # Send it using local path mapping
                        container_tmp_path = tmp_path.replace(TELEGRAM_DATA_HOST_DIR, TELEGRAM_DATA_CONTAINER_DIR).replace('\\', '/')
                        
                        # Use local file path directly for Telegram Bot API Server
                        # aiogram handles FSInputFile efficiently if the session knows it's a local API server
                        from aiogram.types import FSInputFile
                        try:
                            await original_message.reply_video(video=FSInputFile(container_tmp_path))
                        except Exception as e:
                            logger.error(f"Error sending video: {e}")
                            await original_message.reply("✅ Dubbing completed, but failed to send the video file back.")
                        finally:
                            if os.path.exists(tmp_path):
                                os.remove(tmp_path)
                    else:
                        await status_msg.edit_text(f"✅ Dubbing completed, but failed to fetch download url: {resp.text}")
                break
                
            elif status == "failed":
                error_msg = data.get("error", "Unknown error")
                await status_msg.edit_text(f"❌ Dubbing failed: {error_msg}")
                break
                
            else:
                # Still running
                await status_msg.edit_text(f"🔄 Dubbing in progress... (Status: {status}, Progress: {progress}%)")
                await asyncio.sleep(10)

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.reply("Welcome to the Dubbing Bot! Send me a video file (up to 2GB) and I will dub it for you.")

@dp.message(F.video | F.document)
async def handle_video(message: types.Message):
    if message.video:
        file_id = message.video.file_id
        file_size = message.video.file_size
    elif message.document and message.document.mime_type and message.document.mime_type.startswith('video/'):
        file_id = message.document.file_id
        file_size = message.document.file_size
    else:
        await message.reply("Please send a valid video file.")
        return

    # Telegram Bot API can handle up to 2000 MB (which is ~2GB)
    if file_size > 2000 * 1024 * 1024:
        await message.reply("File is too large! Maximum allowed size is 2GB.")
        return

    msg = await message.reply("Downloading video...")
    
    try:
        file = await bot.get_file(file_id)
        file_path = file.file_path
        
        # Translate container path to host path
        if file_path.startswith(TELEGRAM_DATA_CONTAINER_DIR):
            local_path = file_path.replace(TELEGRAM_DATA_CONTAINER_DIR, TELEGRAM_DATA_HOST_DIR)
            local_path = os.path.normpath(local_path)
        else:
            if not os.path.isabs(file_path):
                local_path = os.path.join(TELEGRAM_DATA_HOST_DIR, file_path)
            else:
                local_path = file_path
                
        if not os.path.exists(local_path):
            await msg.edit_text(f"Failed to locate downloaded file on disk. Path: {local_path}")
            return
            
        await msg.edit_text("Video downloaded! Submitting to dubbing pipeline...")
        
        # Submit to backend
        job = await post_video_to_backend(local_path, message)
        
        if job and "id" in job:
            job_id = job["id"]
            # Start polling
            asyncio.create_task(poll_job_status(job_id, msg, message))
        
    except Exception as e:
        logger.exception("Error handling video")
        await message.reply(f"An error occurred: {str(e)}")

async def main():
    logger.info("Starting bot...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
