import asyncio
import os
from convex import ConvexClient

convex_url = os.getenv("CONVEX_URL", "http://127.0.0.1:3210")

async def main():
    client = ConvexClient(convex_url)
    jobs = client.query("dubbingJobs:getAllForDebug", {})
    
    # We don't have a getAllForDebug for workspaces. Let's just print unique ownerUserIds from jobs.
    owners = set()
    workspaces = set()
    for job in jobs:
        owners.add(job.get('ownerUserId'))
        workspaces.add(job.get('workspaceId'))
        
    print(f"Unique Owners: {owners}")
    print(f"Unique Workspaces: {workspaces}")

if __name__ == "__main__":
    asyncio.run(main())
