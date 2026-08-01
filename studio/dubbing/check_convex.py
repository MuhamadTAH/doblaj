import asyncio
import os
from dotenv import load_dotenv
load_dotenv()
from app.core import database_convex

async def main():
    jobs = await database_convex.list_jobs_by_status(status='completed', limit=20)
    for j in jobs:
        r2 = j.get('result_video_r2_key')
        path = r2.lstrip('/') if r2 and r2.startswith('/static') else r2
        exists = os.path.exists(path) if path else False
        print({'id': j.get('id'), 'r2': r2, 'exists': exists})

if __name__ == "__main__":
    asyncio.run(main())
