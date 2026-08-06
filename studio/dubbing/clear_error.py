import asyncio
import os
from convex import ConvexClient

async def main():
    prod_url = "https://upbeat-scorpion-447.convex.cloud"
    internal_key = "145534d5f41b80429286b485055cc6376c7b55bbdd79641eba65b7cbece80a5d"
    
    client = ConvexClient(prod_url)
    try:
        job_id = "jn75ds1jg9p2c61n0y5tnaa78d8bray8" # This is the job ID from the database
        args = {
            "jobId": job_id, 
            "status": "completed", 
            "error": "", 
            "__internalApiKey": internal_key
        }
        
        job = client.mutation("dubbingJobs:updateStatusInternal", args)
        print("Cleared error for JOB!")
        print(job)
    except Exception as e:
        print(f"Failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())
