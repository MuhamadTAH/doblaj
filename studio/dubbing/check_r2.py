import os
import sys
import asyncio
from dotenv import load_dotenv

# Load env before importing app modules
load_dotenv()
# Fallback to production if not set locally
if not os.environ.get("CONVEX_URL"):
    os.environ["CONVEX_URL"] = "https://upbeat-scorpion-447.convex.cloud"

from app.services import r2

def main():
    if len(sys.argv) < 3:
        print("Usage: python check_r2.py <job_id> <workspace_id>")
        sys.exit(1)

    job_id = sys.argv[1]
    workspace_id = sys.argv[2]
    
    # Check for the intermediate zip (uploaded by RunPod GPU phase)
    intermediate_key = r2.dubbing_key(workspace_id, job_id, f"intermediate_{job_id}.zip")
    print(f"Checking for RunPod intermediate artifact: {intermediate_key}")
    
    if r2.exists(intermediate_key):
        print("[SUCCESS] The RunPod worker successfully sent the intermediate zip back to R2.")
    else:
        print("[MISSING] The intermediate zip is not in R2 yet. RunPod might still be processing or failed.")
        
    # Check for the final video (uploaded by Azure CPU phase)
    final_video_key = r2.dubbing_key(workspace_id, job_id, "dubbed_1.mp4")
    print(f"\nChecking for Azure final video artifact: {final_video_key}")
    
    if r2.exists(final_video_key):
        print("[SUCCESS] The Azure worker successfully sent the final video back to R2.")
    else:
        print("[MISSING] The final video is not in R2 yet. Azure CPU phase might still be processing or failed.")

if __name__ == "__main__":
    main()
