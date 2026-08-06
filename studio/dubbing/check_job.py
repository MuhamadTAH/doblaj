import asyncio
import sys
import os
from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.path.dirname(__file__))

import app.core.database_convex as db

async def main():
    ids = ["jn7fdankehkk9dywkd15q795bh8btevw", "b548575c-0eee-4080-b687-56d0f3722708"]
    for job_id in ids:
        print(f"Checking job: {job_id}")
        try:
            job = await db.get_job(job_id=job_id)
            print("Result:", job)
        except Exception as e:
            print("Error:", e)
        print("-" * 20)

if __name__ == "__main__":
    asyncio.run(main())
