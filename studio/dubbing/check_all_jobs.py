import asyncio
import os
from convex import ConvexClient
from dotenv import load_dotenv

load_dotenv('.env')
if not os.environ.get("CONVEX_URL"):
    os.environ["CONVEX_URL"] = "https://upbeat-scorpion-447.convex.cloud"

async def main():
    client = ConvexClient(os.environ["CONVEX_URL"])
    try:
        jobs = client.query("debugJobs:getAll", {})
        jobs.sort(key=lambda x: x.get("_creationTime", 0), reverse=True)
        job = jobs[0]
        print(job)
    except Exception as e:
        print(f"Failed: {e}")

asyncio.run(main())
