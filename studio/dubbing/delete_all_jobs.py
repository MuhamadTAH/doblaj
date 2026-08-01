import os
import asyncio
from convex import ConvexClient
from dotenv import load_dotenv

load_dotenv("d:/Pird/studio/dubbing/.env")

CONVEX_URL = os.getenv("CONVEX_URL", "http://127.0.0.1:3210")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")

async def main():
    if not INTERNAL_API_KEY:
        print("Error: INTERNAL_API_KEY not found in .env")
        return
    
    print(f"Connecting to {CONVEX_URL}...")
    client = ConvexClient(CONVEX_URL)
    
    print("Calling adminTasks:deleteAllInternal...")
    try:
        deleted_count = client.mutation("adminTasks:deleteAllInternal", {"__internalApiKey": INTERNAL_API_KEY})
        print(f"Success! Deleted {deleted_count} jobs.")
    except Exception as e:
        print(f"Error calling mutation: {e}")

if __name__ == "__main__":
    asyncio.run(main())
