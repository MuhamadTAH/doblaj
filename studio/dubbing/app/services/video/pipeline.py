def create_video_job(*args, **kwargs):
    return {"job_id": "mock_id", "status": "pending"}

def get_job_status(*args, **kwargs):
    return {"job_id": "mock_id", "status": "completed", "progress": 100}
