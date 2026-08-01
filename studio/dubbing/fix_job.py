import asyncio
import os
from dotenv import load_dotenv
load_dotenv()
from app.core import database_convex

async def main():
    c = database_convex._get_client()
    jid = "jh71dt5t0vvdjhdpnq3prp0f7s8bhxv2"
    
    args = {
        "jobId": jid,
        "status": "completed",
        "resultVideoR2Key": "/static/outputs/dubbed_14.mp4"
    }
    
    try:
        res = c.mutation("dubbingJobs:updateStatusInternal", database_convex._internal_args(args))
        print("Update response:", res)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
