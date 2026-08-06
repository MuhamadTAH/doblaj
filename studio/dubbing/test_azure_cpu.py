import asyncio
import os
import sys
import logging
from dotenv import load_dotenv

# Load env before importing app modules
load_dotenv()

from app.services import r2
from app.services.video_worker_vcta import process_video_cpu_phase
from app.core.db import _get_service_role_client # Just to ensure we have imports

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    if len(sys.argv) < 3:
        print("Usage: python test_azure_cpu.py <job_id> <workspace_id>")
        sys.exit(1)

    job_id = sys.argv[1]
    workspace_id = sys.argv[2]
    
    r2_key = f"dubbing/{workspace_id}/{job_id}/intermediate_{job_id}.zip"
    
    local_zip = f"data/temp/{job_id}_intermediate.zip"
    os.makedirs(os.path.dirname(local_zip), exist_ok=True)
    
    logger.info(f"Downloading R2 Key: {r2_key} to {local_zip}")
    try:
        r2.download_file(r2_key, local_zip)
        logger.info("Download complete.")
    except Exception as e:
        logger.error(f"Failed to download from R2: {e}")
        return
        
    logger.info("Running CPU Phase...")
    try:
        final_path = await process_video_cpu_phase(local_zip)
        logger.info(f"CPU Phase completed successfully. Final path: {final_path}")
    except Exception as e:
        logger.error(f"CPU Phase failed: {e}", exc_info=True)

if __name__ == "__main__":
    asyncio.run(main())
