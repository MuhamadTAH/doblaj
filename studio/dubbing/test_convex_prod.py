import asyncio
import os
from convex import ConvexClient
from app.core import database_convex

async def main():
    # Use the prod Convex URL and internal API key from .env
    prod_url = "https://upbeat-scorpion-447.convex.cloud"
    internal_key = "145534d5f41b80429286b485055cc6376c7b55bbdd79641eba65b7cbece80a5d"
    os.environ["INTERNAL_API_KEY"] = internal_key
    
    client = ConvexClient(prod_url)
    try:
        job_id = "e8ebaf13-35db-446b-9079-68852f8486e3"
        args = {"jobId": job_id, "__internalApiKey": internal_key}
        # The mutation returns the job doc!
        # Oh wait, we shouldn't mutate. Let's try to query it.
        # But getInternal is not exported. Let's look at database_convex.py.
        # It uses: c.query("dubbingJobs:getInternal", _internal_args(args))
        job = client.query("dubbingJobs:getInternal", args)
        print("JOB FROM PROD CONVEX:")
        print(job)
    except Exception as e:
        print(f"Failed: {e}")
        import traceback
        traceback.print_exc()

asyncio.run(main())
