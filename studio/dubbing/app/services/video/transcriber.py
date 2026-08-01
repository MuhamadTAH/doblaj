import asyncio
import subprocess
import os

async def extract_audio(video_path: str, output_path: str):
    # Pird: validate paths are under our workspace root. See pass-4 review.
    from pathlib import Path as _Path
    _allowed = _Path("data/jobs/sessions").resolve()
    _vp = _Path(video_path).resolve()
    if not _vp.is_relative_to(_allowed):
        raise ValueError(f"video_path must be under {_allowed}, got {_vp}")
    _op = _Path(output_path).resolve()
    if not _op.is_relative_to(_allowed):
        raise ValueError(f"output_path must be under {_allowed}, got {_op}")

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-q:a", "0",
        "-map", "a",
        output_path
    ]
    # Pird: bind subprocess.run directly into to_thread. No behavior change.
    proc = await asyncio.to_thread(
        subprocess.run, cmd,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    if proc.returncode == 0 and os.path.exists(output_path):
        return True, output_path
    return False, None
