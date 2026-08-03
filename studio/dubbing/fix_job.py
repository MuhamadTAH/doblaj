import asyncio
import os
from dotenv import load_dotenv
load_dotenv()
from app.core import database_convex

async def main():
    c = database_convex._get_client()
    jid = "b548575c-0eee-4080-b687-56d0f3722708"
    
    args = {
        "legacyId": jid
    }
    
    try:
        res = c.mutation("tempQuery:forceUpdate", args)
        print("Update response:", res)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
