import asyncio
import os
from convex import ConvexClient

async def main():
    prod_url = "https://upbeat-scorpion-447.convex.cloud"
    internal_key = "145534d5f41b80429286b485055cc6376c7b55bbdd79641eba65b7cbece80a5d"
    os.environ["INTERNAL_API_KEY"] = internal_key
    
    client = ConvexClient(prod_url)
    try:
        job_id = "b548575c-0eee-4080-b687-56d0f3722708"
        args = {"jobId": job_id, "__internalApiKey": internal_key}
        
        job = client.query("dubbingJobs:getInternal", args)
        print("JOB STATUS FROM CONVEX:")
        print(f"ID: {job.get('_id')}")
        print(f"Status: {job.get('status')}")
        print(f"Error: {job.get('error')}")
        print(f"VideoR2Key: {job.get('resultVideoR2Key')}")
        print(f"Progress: {job.get('progress')}")
    except Exception as e:
        print(f"Failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
