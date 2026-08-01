"""
Test script to verify Convex database integration locally before building/deploying Docker image.
"""
import os
import sys
import asyncio
import logging

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core import db as database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_convex")

async def main():
    logger.info("--- Testing Database Switcher ---")
    logger.info(f"DATA_BACKEND: {os.getenv('DATA_BACKEND', 'not set')}")
    logger.info(f"CONVEX_URL: {os.getenv('CONVEX_URL', 'not set')}")
    logger.info(f"SUPABASE_URL: {os.getenv('SUPABASE_URL', 'not set')}")
    
    test_ws = "ws_test_123"
    test_user = "user_test_123"
    test_key = "inputs/test_video.mp4"

    try:
        logger.info("\n1. Testing create_job()...")
        job = await database.create_job(
            workspace_id=test_ws,
            owner_user_id=test_user,
            source_video_r2_key=test_key
        )
        logger.info(f"Job Created Successfully! Record: {job}")
        job_id = job.get("id") or "test_job_id"

        logger.info("\n2. Testing update_job_status()...")
        await database.update_job_status(
            workspace_id=test_ws,
            job_id=job_id,
            status="separating",
            progress=25
        )
        logger.info("Job Status Updated to 'separating' (25%)!")

        logger.info("\n3. Testing get_job()...")
        fetched = await database.get_job(workspace_id=test_ws, job_id=job_id)
        logger.info(f"Fetched Job Record: {fetched}")

        logger.info("\n4. Testing update_job_status() with final output R2 key...")
        await database.update_job_status(
            workspace_id=test_ws,
            job_id=job_id,
            status="done",
            progress=100,
            output_path=f"outputs/dubbed_{job_id}.mp4"
        )
        logger.info("Job marked as 'done' (100%) successfully!")

        logger.info("\n✅ ALL CONVEX DATABASE TESTS PASSED SUCCESSFULLY!")

    except Exception as e:
        logger.error(f"\n❌ Test failed with error: {e}", exc_info=True)

if __name__ == "__main__":
    asyncio.run(main())
