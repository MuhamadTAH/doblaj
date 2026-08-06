import os
from convex import ConvexClient
import uuid

CONVEX_URL = "https://upbeat-scorpion-447.convex.cloud"
INTERNAL_API_KEY = "145534d5f41b80429286b485055cc6376c7b55bbdd79641eba65b7cbece80a5d"

client = ConvexClient(CONVEX_URL)

try:
    print("Testing createInternal...")
    legacy_id = str(uuid.uuid4())
    res = client.mutation("dubbingJobs:createInternal", {
        "workspaceId": "jn7fdankehkk9dywkd15q795bh8btevw",
        "legacyId": legacy_id,
        "__internalApiKey": INTERNAL_API_KEY
    })
    print(f"createInternal returned: {res}")
    
    convex_id = res["_id"]
    print(f"\nTesting getInternal with Convex ID: {convex_id}")
    res2 = client.query("dubbingJobs:getInternal", {
        "jobId": convex_id,
        "__internalApiKey": INTERNAL_API_KEY
    })
    print(f"getInternal with Convex ID returned: {res2}")
    
    print(f"\nTesting getInternal with Legacy ID: {legacy_id}")
    res3 = client.query("dubbingJobs:getInternal", {
        "jobId": legacy_id,
        "__internalApiKey": INTERNAL_API_KEY
    })
    print(f"getInternal with Legacy ID returned: {res3}")
    
except Exception as e:
    print(f"Error type: {type(e)}")
    print(f"Error args: {e.args}")
    print(f"Dir of e: {dir(e)}")
    if hasattr(e, 'message'):
        print(e.message)
    if hasattr(e, 'data'):
        print(e.data)
