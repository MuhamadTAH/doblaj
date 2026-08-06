import asyncio
import os
import sys
from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.path.dirname(__file__))

from app.services import r2
from app.core import database_convex as database

async def main():
    print("Checking R2 for intermediate zips from RunPod...")
    client = r2._client()
    try:
        # List objects under the "dubbing/" prefix
        response = client.list_objects_v2(Bucket=r2.R2_BUCKET, Prefix="dubbing/")
        
        if "Contents" not in response:
            print("No files found in R2 under 'dubbing/' prefix.")
            return

        intermediate_files = []
        for obj in response["Contents"]:
            key = obj["Key"]
            if "intermediate_" in key and key.endswith(".zip"):
                intermediate_files.append(key)
        
        print(f"Found {len(intermediate_files)} intermediate zip files in R2.")
        
        for key in intermediate_files:
            # key format: dubbing/{workspace_id}/{job_id}/intermediate_{job_id}.zip
            parts = key.split("/")
            if len(parts) >= 4:
                workspace_id = parts[1]
                job_id = parts[2]
                
                print(f"\nChecking job {job_id} in Convex...")
                try:
                    # Check current job status
                    job = await database.get_job(workspace_id=workspace_id, job_id=job_id)
                    if not job:
                        print(f"Job {job_id} not found in Convex. Skipping.")
                        continue
                    
                    status = job.get("status")
                    print(f"Current status: {status}")
                    
                    if status in ["pending", "processing"]:
                        print(f"RunPod finished this job (zip is in R2) but status is '{status}'. Bridging...")
                        
                        await database.update_job_status(
                            workspace_id=workspace_id,
                            job_id=job_id,
                            status="gpu_finished",
                            progress=50,
                            output_path=key,
                        )
                        print(f"Updated job {job_id} to 'gpu_finished' successfully!")
                    else:
                        print(f"Job {job_id} is already past the GPU phase (status: {status}). No action needed.")
                
                except Exception as e:
                    print(f"Error updating job {job_id}: {e}")
                    
    except Exception as e:
        print(f"Error accessing R2: {e}")

if __name__ == "__main__":
    asyncio.run(main())
