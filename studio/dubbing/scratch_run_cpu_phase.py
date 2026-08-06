import asyncio
import os
import sys
import logging
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.DEBUG, stream=sys.stdout)
logging.getLogger("httpx").setLevel(logging.WARNING) # reduce httpx spam

load_dotenv()
from app.services.video_worker_vcta import process_video_cpu_phase

async def main():
    try:
        await process_video_cpu_phase(r'd:\Pird\studio\dubbing\data\jobs\sessions\4.zip')
    except Exception as e:
        logging.exception("Failed")

asyncio.run(main())
