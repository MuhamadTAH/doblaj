import os
import sys
import asyncio
import json
from dotenv import load_dotenv

load_dotenv(r"d:\Pird\studio\dubbing\.env")
sys.path.append(r"d:\Pird\studio\dubbing")
from app.core import db as database
from app.schemas.video import VideoJobResponse

async def main():
    client = database._get_service_role_client()
    workspace_id = "org_3Gqh0tJsDrEn6YFh95nhqR78AKE"
    jobs = await database.list_jobs(client, workspace_id=workspace_id)
    
    responses = []
    for job in jobs:
        try:
            resp = VideoJobResponse(
                id=job["id"],
                store_id="", 
                status="completed" if job["status"] == "done" else job["status"],
                progress=job.get("progress", 0) or 0,
                input_path="",  
                output_path=job.get("result_video_r2_key") or "",
                created_at=str(job.get("created_at", "")),
                updated_at=str(job.get("updated_at", "")),
            ).model_dump()
            responses.append(resp)
        except Exception as e:
            print(f"Error mapping job {job.get('id')}: {e}")
            
    print(json.dumps(responses, indent=2))

if __name__ == "__main__":
    asyncio.run(main())
