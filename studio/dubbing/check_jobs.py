import asyncio
import os
from dotenv import load_dotenv
load_dotenv()
from app.core import database_convex

async def main():
    job_ids = ["jh77rnhzqptzycqn2hpscee9z58bh98g", "jh71dt5t0vvdjhdpnq3prp0f7s8bhxv2"]
    
    # Let's bypass the swallowed exception in get_job and do it manually
    c = database_convex._get_client()
    for jid in job_ids:
        print(f"\nChecking job: {jid}")
        try:
            args = {"jobId": jid}
            raw = c.query("dubbingJobs:getInternal", database_convex._internal_args(args))
            print(f"Raw job: {raw}")
            if raw:
                r2 = raw.get('resultVideoR2Key')
                path = r2.lstrip('/') if r2 and r2.startswith('/static') else r2
                if path and not path.startswith('/static'):
                    path = r2.lstrip('/')
                exists = os.path.exists(path) if path else False
                print({'id': raw.get('_id'), 'r2': r2, 'exists': exists, 'path': path})
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
