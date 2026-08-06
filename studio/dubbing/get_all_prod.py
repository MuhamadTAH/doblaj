import asyncio
import os
from app.core import database_convex

def main():
    os.environ["CONVEX_URL"] = "https://upbeat-scorpion-447.convex.cloud"
    c = database_convex._get_client()
    try:
        raw = c.query("debugWorkspaces:getAll", {})
        print(f"Total workspaces: {len(raw)}")
        for r in raw:
            print(f"ID: {r.get('_id')} | Legacy: {r.get('legacyId')} | Name: {r.get('name')}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
