import asyncio
from dotenv import load_dotenv
load_dotenv()
from app.core import database_convex

def main():
    c = database_convex._get_client()
    try:
        raw = c.query("dubbingJobs:getAllForDebug", {})
        for r in raw:
            print(f"ID: {r.get('_id')} | Legacy: {r.get('legacyId')} | Status: {r.get('status')}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
