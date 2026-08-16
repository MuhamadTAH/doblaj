import os
import sys
import logging
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Load environment variables
load_dotenv()

# Configure lightweight logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("doblaj.mcp.standalone")

# Import only the pure dubbing engine & storage manager
from app.mcp.pipeline_engine import DubbingPipelineEngine
from app.mcp.storage import ScratchManager

# Instantiate the Standalone Dubbing MCP Server
mcp = FastMCP(
    name="doblaj-dubbing",
    instructions="Doblaj Dedicated Video Dubbing MCP Engine (Kurdish Sorani -> Spoken Iraqi Arabic)"
)


@mcp.tool(name="separate_and_chunk_video")
async def separate_and_chunk_video(job_id: str, video_path: str) -> dict:
    """
    Stage 1 & 2: Stem separation, VAD pause detection, master voice anchor extraction, and chunk creation.
    
    Args:
        job_id: Unique job identifier (e.g. 'job_123')
        video_path: Local path or R2 key of the source MP4 video
    """
    return await DubbingPipelineEngine.separate_and_chunk(job_id, video_path)


@mcp.tool(name="transcribe_kurdish_chunks")
async def transcribe_kurdish_chunks(job_id: str) -> dict:
    """
    Stage 3: Dual-Pass Global Reference Kurdish Sorani Speech-to-Text.
    
    Args:
        job_id: Unique job identifier
    """
    return await DubbingPipelineEngine.transcribe_kurdish(job_id)


@mcp.tool(name="translate_and_calibrate_iraqi")
async def translate_and_calibrate_iraqi(job_id: str, retry_count: int = 0) -> dict:
    """
    Stage 4: Spoken Iraqi Arabic Localization with 100% Phonetic Number Words and 2-Retry Speed Calibration Circuit Breaker.
    
    Args:
        job_id: Unique job identifier
        retry_count: Current retry iteration (Max: 2)
    """
    return await DubbingPipelineEngine.translate_and_calibrate(job_id, retry_count=retry_count)


@mcp.tool(name="synthesize_and_master_dubbing")
async def synthesize_and_master_dubbing(job_id: str, original_video_path: str, cleanup_scratch: bool = True) -> dict:
    """
    Stage 5, 6 & 7: Single Master Anchor Voice Cloning, Dynamic RMS Energy Envelope Following, Full-Duration Audio Alignment, and Smart Quran Outro Preservation.
    
    Args:
        job_id: Unique job identifier
        original_video_path: Path to original source video
        cleanup_scratch: Whether to delete temporary scratch files on completion (Default: True)
    """
    return await DubbingPipelineEngine.synthesize_and_master(job_id, original_video_path)


@mcp.tool(name="run_full_dubbing_job")
async def run_full_dubbing_job(job_id: str, video_path: str) -> dict:
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


if __name__ == "__main__":
    # Support both Stdio (default for CLI) and SSE mode
    if "--sse" in sys.argv:
        port = int(os.getenv("MCP_PORT", "8005"))
        print(f"Starting Standalone FastMCP SSE server on port {port}...")
        mcp.run(transport="sse", port=port)
    else:
        mcp.run(transport="stdio")
