import os
import asyncio
from app.core import database_convex as database

async def main():
    import uuid
    actual_job_id = str(uuid.uuid4())
    print(f"Creating job with legacy ID: {actual_job_id}")
    job = await database.create_job(
        workspace_id="test_workspace_" + actual_job_id[:8],
        owner_user_id="user_2bFf3yX",
        job_id=actual_job_id,
        source_video_r2_key="test_key"
    )
    print(f"Created job: {job}")
    
    # Try retrieving it using the Convex ID
    convex_id = job.get("id")
    print(f"\nRetrieving job by Convex ID: {convex_id}")
    job_by_convex = await database.get_job(workspace_id=job.get("workspace_id"), job_id=convex_id)
    print(f"Found job: {job_by_convex}")
    
    # Try retrieving it using the legacy ID
    print(f"\nRetrieving job by Legacy ID: {actual_job_id}")
    job_by_legacy = await database.get_job(workspace_id=job.get("workspace_id"), job_id=actual_job_id)
    print(f"Found job: {job_by_legacy}")
    
if __name__ == "__main__":
    asyncio.run(main())
