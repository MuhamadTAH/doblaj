import os
from convex import ConvexClient

CONVEX_URL = "https://upbeat-scorpion-447.convex.cloud"
INTERNAL_API_KEY = "145534d5f41b80429286b485055cc6376c7b55bbdd79641eba65b7cbece80a5d"

client = ConvexClient(CONVEX_URL)

try:
    print("Testing getInternal...")
    res = client.query("dubbingJobs:getInternal", {
        "jobId": "invalid-id",
        "__internalApiKey": INTERNAL_API_KEY
    })
    print(res)
except Exception as e:
    print(f"Error type: {type(e)}")
    print(f"Error args: {e.args}")
    print(f"Dir of e: {dir(e)}")
    if hasattr(e, 'message'):
        print(e.message)
    if hasattr(e, 'data'):
        print(e.data)
