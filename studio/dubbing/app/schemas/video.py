from pydantic import BaseModel
from typing import Optional


class VideoJobCreate(BaseModel):
    video_url: str
    store_id: Optional[str] = None


class VideoJobResponse(BaseModel):
    id: str
    store_id: str = ""
    status: str
    progress: int = 0
    input_path: str = ""
    output_path: str = ""
    error: str = ""
    created_at: str = ""
    updated_at: str = ""
    message: Optional[str] = None


class VideoJobStatus(BaseModel):
    id: str
    status: str
    progress: int = 0
    input_path: str = ""
    output_path: str = ""
    error: str = ""
    created_at: str = ""
    updated_at: str = ""
    message: Optional[str] = None
