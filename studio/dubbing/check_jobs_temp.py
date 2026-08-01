import asyncio
from app.core import database_convex as backend

async def main():
    client = backend._get_service_role_client()
    jobs = await backend.list_jobs(client, workspace_id='org_3Gqh0tJsDrEn6YFh95nhqR78AKE')
    for j in jobs:
        print(f"Job {j.get('id')} - Status: {j.get('status')} - Output: {j.get('result_video_r2_key')}")

asyncio.run(main())
