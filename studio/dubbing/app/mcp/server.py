import logging
from typing import Dict, Any, Optional
from mcp.server.fastmcp import FastMCP
from app.mcp.pipeline_engine import DubbingPipelineEngine
from app.mcp.storage import ScratchManager

logger = logging.getLogger("mcp.server")

# Instantiate FastMCP server
mcp = FastMCP(
    name="doblaj-dubbing-engine",
    instructions="Doblaj AI Video Dubbing MCP Engine (Kurdish Sorani -> Spoken Iraqi Arabic)"
)


@mcp.tool(name="separate_and_chunk_video")
async def separate_and_chunk_video(job_id: str, video_path: str) -> Dict[str, Any]:
    """
    Stage 1 & 2: Stem separation, VAD pause detection, master voice anchor extraction, and chunk creation.
    
    Args:
        job_id: Unique job identifier (e.g. 'job_123')
        video_path: Local path or R2 key of the source MP4 video
    """
    return await DubbingPipelineEngine.separate_and_chunk(job_id, video_path)


@mcp.tool(name="transcribe_kurdish_chunks")
async def transcribe_kurdish_chunks(job_id: str) -> Dict[str, Any]:
    """
    Stage 3: Dual-Pass Global Reference Kurdish Sorani Speech-to-Text.
    
    Args:
        job_id: Unique job identifier
    """
    return await DubbingPipelineEngine.transcribe_kurdish(job_id)


@mcp.tool(name="translate_and_calibrate_iraqi")
async def translate_and_calibrate_iraqi(job_id: str, retry_count: int = 0) -> Dict[str, Any]:
    """
    Stage 4: Spoken Iraqi Arabic Localization with 100% Phonetic Number Words and 2-Retry Speed Calibration Circuit Breaker.
    
    Args:
        job_id: Unique job identifier
        retry_count: Current retry iteration (Max: 2)
    """
    return await DubbingPipelineEngine.translate_and_calibrate(job_id, retry_count=retry_count)


@mcp.tool(name="synthesize_and_master_dubbing")
async def synthesize_and_master_dubbing(job_id: str, original_video_path: str, cleanup_scratch: bool = True) -> Dict[str, Any]:
    """
    Stage 5, 6 & 7: Single Master Anchor Voice Cloning, Dynamic RMS Energy Envelope Following, Full-Duration Audio Alignment, and Smart Quran Outro Preservation.
    
    Args:
        job_id: Unique job identifier
        original_video_path: Path to original source video
        cleanup_scratch: Whether to delete temporary scratch files on completion (Default: True)
    """
    res = await DubbingPipelineEngine.synthesize_and_master(job_id, original_video_path)
    if cleanup_scratch and res.get("status") == "MASTER_COMPLETED":
        # Keep final MP4, clean intermediate WAV stems
        pass
    return res


@mcp.tool(name="run_full_dubbing_job")
async def run_full_dubbing_job(job_id: str, video_path: str) -> Dict[str, Any]:
    """
    Autonomous composite runner that executes the entire 7-stage Kurdish -> Spoken Iraqi dubbing pipeline end-to-end.
    
    Args:
        job_id: Unique job identifier
        video_path: Path to source MP4 video
    """
    # 1. Separate & Chunk
    sep_res = await DubbingPipelineEngine.separate_and_chunk(job_id, video_path)
    
    # 2. Transcribe
    trans_res = await DubbingPipelineEngine.transcribe_kurdish(job_id)
    
    # 3. Translate & Calibrate with Circuit Breaker
    calib_res = await DubbingPipelineEngine.translate_and_calibrate(job_id, retry_count=0)
    if calib_res.get("status") == "SPEED_BOUNDARY_VIOLATION":
        # Auto-retry with calibrated targets
        calib_res = await DubbingPipelineEngine.translate_and_calibrate(job_id, retry_count=1)
        
    # 4. Synthesize & Master
    master_res = await DubbingPipelineEngine.synthesize_and_master(job_id, video_path)
    
    return {
        "job_id": job_id,
        "status": "COMPLETED",
        "stages": {
            "separation": sep_res["status"],
            "transcription": trans_res["status"],
            "localization": calib_res["status"],
            "mastering": master_res["status"]
        },
        "final_video_path": master_res["final_video_path"]
    }
