import asyncio
from pathlib import Path
from app.services.vcta.assembler import assemble_final_video
from app.services.vcta.audio_pipeline import compile_final_video

import json

async def main():
    session_dir = Path("data/jobs/sessions/16")
    with open(session_dir / "job_details.json", encoding="utf-8") as f:
        chunks = json.load(f)
        
    bg_wav = str(session_dir / "1-separation" / "background.wav")
    video_path = str(session_dir / "video.mp4")
    
    # Check if files exist
    print("bg_wav exists:", Path(bg_wav).exists())
    print("video_path exists:", Path(video_path).exists())
    
    try:
        await assemble_final_video(
            chunks=chunks,
            background_wav=bg_wav,
            video_path=video_path,
            work_dir=str(session_dir),
            reference_profile=None
        )
    except Exception as e:
        print("ERROR:", e)

if __name__ == "__main__":
    asyncio.run(main())
