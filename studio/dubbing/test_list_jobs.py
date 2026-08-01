import os
import sys
import asyncio
from dotenv import load_dotenv

load_dotenv(r"d:\Pird\studio\dubbing\.env")
sys.path.append(r"d:\Pird\studio\dubbing")
from app.core import db as database

async def main():
    client = database._get_service_role_client()
    workspace_id = "org_3Gqh0tJsDrEn6YFh95nhqR78AKE"
    jobs = await database.list_jobs(client, workspace_id=workspace_id)
    if jobs:
        print("First job from DB:", jobs[0])
        print("ID:", jobs[0].get("id"))
        print("_ID:", jobs[0].get("_id"))
        print("Status mapping test:", "completed" if jobs[0]["status"] == "done" else jobs[0]["status"])

if __name__ == "__main__":
    asyncio.run(main())
