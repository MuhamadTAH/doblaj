import asyncio
import os
from convex import ConvexClient

convex_url = os.getenv("CONVEX_URL", "http://127.0.0.1:3210")

async def main():
    client = ConvexClient(convex_url)
    workspaces = client.query("workspaces:getAllForDebug", {})
    
    for ws in workspaces:
        print(f"WorkspaceID (legacyId): {ws.get('legacyId')}")
        print(f"Name: {ws.get('name')}")
        print(f"OwnerUserID: {ws.get('ownerUserId')}")
        print("-" * 40)

if __name__ == "__main__":
    asyncio.run(main())
