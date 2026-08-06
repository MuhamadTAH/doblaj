import asyncio
import os
from convex import ConvexClient

async def main():
    prod_url = "https://upbeat-scorpion-447.convex.cloud"
    internal_key = "145534d5f41b80429286b485055cc6376c7b55bbdd79641eba65b7cbece80a5d"
    
    client = ConvexClient(prod_url)
    try:
        args = {"status": "separating", "limit": 10, "__internalApiKey": internal_key}
        jobs = client.query("dubbingJobs:listByStatusInternal", args)
        print(f"Jobs with status 'separating': {len(jobs)}")
        for job in jobs:
            print(f"Job ID: {job.get('legacyId')}, Progress: {job.get('progress')}, Status: {job.get('status')}")
    except Exception as e:
        print(f"Failed: {e}")
        import traceback
        traceback.print_exc()

asyncio.run(main())
