import os
import sys

from app.core.database_convex import _get_client, _internal_args

# e8ebaf13-35db-446b-9079-68852f8486e3 was the job ID in the user's logs
JOB_ID = "e8ebaf13-35db-446b-9079-68852f8486e3"

def test_update():
    c = _get_client()
    try:
        args = {"jobId": JOB_ID}
        print(f"Calling getInternal with args: {args}")
        raw = c.query("dubbingJobs:getInternal", _internal_args(args))
        print("Job fetched:", raw)
    except Exception as e:
        print(f"Fetch failed with exception:\n{e}")

    try:
        args = {
            "jobId": JOB_ID,
            "status": "testing",
            "progress": 20,
        }
        print(f"Calling dubbingJobs:updateStatusInternal with args: {args}")
        res = c.mutation("dubbingJobs:updateStatusInternal", _internal_args(args))
        print("Update succeeded:", res)
    except Exception as e:
        print(f"Update failed with exception:\n{e}")

if __name__ == "__main__":
    test_update()
