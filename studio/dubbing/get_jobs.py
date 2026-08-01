import sys, asyncio, os
from dotenv import load_dotenv
load_dotenv('.env')
sys.path.insert(0, 'd:/Pird/studio/dubbing')
from app.core import db
async def main():
    res = await db.list_jobs(workspace_id='org_3Gqh0tJsDrEn6YFh95nhqR78AKE')
    print('Jobs count:', len(res) if res else 0)
    for j in res or []: print(j.get('id'), j.get('status'), j.get('progress'))
asyncio.run(main())
