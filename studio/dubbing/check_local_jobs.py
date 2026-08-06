import asyncio
import os
from convex import ConvexClient
from dotenv import load_dotenv

load_dotenv('.env')

async def main():
    client = ConvexClient(os.environ.get("CONVEX_URL", "http://127.0.0.1:3210"))
    try:
        jobs = client.query("debugJobs:getAll", {})
        print(f"Total jobs: {len(jobs)}")
        jobs.sort(key=lambda x: x.get("_creationTime", 0), reverse=True)
        for job in jobs[:10]:
            print(f"ID: {job.get('legacyId', job.get('_id'))} | Status: {job.get('status')} | Worker: {job.get('assignedWorker')} | Progress: {job.get('progress')}")
    except Exception as e:
        print(f"Failed: {e}")

asyncio.run(main())
