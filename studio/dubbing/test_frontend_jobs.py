import os
import sys
import asyncio
from dotenv import load_dotenv

load_dotenv(r"d:\Pird\studio\dubbing\.env")
sys.path.append(r"d:\Pird\studio\dubbing")
from app.core import db as database

async def main():
    client = database._get_service_role_client()
    # Pird workspaces seem to be 'k57fh2smh2n9r1mzh2phwpgtw18bdfn3' based on previous log
    workspace_id = "org_3Gqh0tJsDrEn6YFh95nhqR78AKE"
    jobs = await database.list_jobs(client, workspace_id=workspace_id)
    active_count = 0
    statuses = set()
    for job in jobs:
        st = "completed" if job.get("status") == "done" else job.get("status")
        statuses.add(st)
        if st not in ("completed", "failed"):
            active_count += 1
            print(f"Active Job: ID={job.get('id')} Status={st}")
            
    print(f"Total jobs: {len(jobs)}")
    print(f"Active jobs count: {active_count}")
    print(f"All returned statuses: {statuses}")

if __name__ == "__main__":
    asyncio.run(main())
