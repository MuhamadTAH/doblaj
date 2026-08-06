import asyncio
import os
import logging
from dotenv import load_dotenv
load_dotenv('.env')
from app.core import db as database

logging.basicConfig(level=logging.INFO)

async def main():
    job_id = "jn7fdankehkk9dywkd15q795bh8btevw"
    print(f"Testing get_job for {job_id}")
    job = await database.get_job(job_id=job_id)
    print(f"Result: {job}")

if __name__ == "__main__":
    asyncio.run(main())
