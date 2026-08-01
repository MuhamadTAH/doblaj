import asyncio
from app.core import db

async def main():
    try:
        jobs = await db.list_jobs(None, "user_2a6z9sH2O1jGv2O8wX2v1V4b4H3") # Fake ID or real ID if we know it
        print("Got", len(jobs), "jobs")
        for j in jobs:
            print(j.get("id"), j.get("status"), j.get("result_video_r2_key"), j.get("output_path"))
    except Exception as e:
        print("Error:", e)

    try:
        jobs2 = await db.list_jobs(None, "ws_2j3F...") # or pass none if not filtered
    except Exception:
        pass
    
    # Actually just print the internal dict if it's database_convex using _in_memory_jobs
    import app.core.database_convex as db_c
    print("In-memory jobs keys:", db_c._in_memory_jobs.keys())
    for k, v in db_c._in_memory_jobs.items():
        print(k, v.get("status"), v.get("result_video_r2_key"), v.get("output_path"))

asyncio.run(main())
