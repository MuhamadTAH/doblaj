import asyncio
import os
from dotenv import load_dotenv
load_dotenv()
from app.core import database_convex
from app.core.database_convex import _get_client, _internal_args

async def test_all():
    c = _get_client()
    try:
        raw = c.query("dubbingJobs:getAllForDebug")
        print("Jobs:")
        for doc in raw:
            print(f"ID: {doc.get('_id')}, LegacyId: {doc.get('legacyId')}, workspaceId: {doc.get('workspaceId')}, createdAt: {doc.get('createdAt')}")
    except Exception as e:
        print(f"Failed:\n{e}")

if __name__ == "__main__":
    asyncio.run(test_all())
