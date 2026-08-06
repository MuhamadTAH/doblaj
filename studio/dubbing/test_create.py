import asyncio
import os
from dotenv import load_dotenv
load_dotenv()
from app.core import database_convex

async def main():
    os.environ["CONVEX_URL"] = "https://upbeat-scorpion-447.convex.cloud"
    print(f"INTERNAL_API_KEY: {os.getenv('INTERNAL_API_KEY')[:10]}...")
    try:
        job = await database_convex.create_job(
            workspace_id="6820c4e7-062e-4946-8f0d-9c26aebcd000",
            owner_user_id="test_user",
            source_video_r2_key="test_key"
        )
        print(f"Job created: {job}")
    except Exception as e:
        print(f"Error creating job: {e}")

if __name__ == "__main__":
    asyncio.run(main())
