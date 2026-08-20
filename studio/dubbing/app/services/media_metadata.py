"""
Media metadata extraction engine using ffprobe.
Probes video containers (directly via streaming URL or local file)
to extract exact duration, resolution, frame rate, audio sample rate, and codecs.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def extract_media_metadata(file_path_or_url: str) -> Dict[str, Any]:
    """
    Run ffprobe on a local video file path or signed R2 HTTPS URL.
    Returns structured media metadata.
    """
    ffprobe_bin = shutil.which("ffprobe") or "ffprobe"

    cmd = [
        ffprobe_bin,
        "-v", "error",
        "-show_entries", "format=duration,size,bit_rate,format_name:stream=width,height,codec_name,codec_type,sample_rate,channels,r_frame_rate,duration",
        "-of", "json",
        file_path_or_url,
    ]

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
            check=False,
        )

        if proc.returncode != 0:
            logger.warning("[METADATA] ffprobe failed with code %d: %s", proc.returncode, proc.stderr.strip())
            return _empty_metadata()

        data = json.loads(proc.stdout)
        fmt = data.get("format", {})
        streams = data.get("streams", [])

        video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
        audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), {})

        duration_sec = 0.0
        try:
            duration_sec = float(fmt.get("duration") or video_stream.get("duration") or audio_stream.get("duration") or 0.0)
        except (ValueError, TypeError):
            duration_sec = 0.0

        width = video_stream.get("width")
        height = video_stream.get("height")
        resolution = f"{width}x{height}" if width and height else None

        # Parse FPS
        fps = None
        r_frame_rate = video_stream.get("r_frame_rate", "")
        if "/" in r_frame_rate:
            try:
                num, den = r_frame_rate.split("/")
                if float(den) > 0:
                    fps = round(float(num) / float(den), 2)
            except Exception:
                fps = None

        # Parse sample rate
        sample_rate = None
        if audio_stream.get("sample_rate"):
            try:
                sample_rate = int(audio_stream["sample_rate"])
            except Exception:
                sample_rate = None

        # Parse channels
        channels = audio_stream.get("channels")
        if channels is not None:
            try:
                channels = int(channels)
            except Exception:
                channels = None

        # File size
        file_size_bytes = None
        try:
            file_size_bytes = int(fmt.get("size") or 0)
        except Exception:
            file_size_bytes = None

        # Bitrate
        bitrate_kbps = None
        try:
            bitrate_kbps = round(int(fmt.get("bit_rate") or 0) / 1000, 1)
        except Exception:
            bitrate_kbps = None

        return {
            "durationSec": round(duration_sec, 3),
            "durationMs": int(duration_sec * 1000),
            "width": width,
            "height": height,
            "resolution": resolution,
            "fps": fps,
            "videoCodec": video_stream.get("codec_name"),
            "audioCodec": audio_stream.get("codec_name"),
            "audioSampleRate": sample_rate,
            "audioChannels": channels,
            "fileSizeBytes": file_size_bytes,
            "bitrateKbps": bitrate_kbps,
            "formatName": fmt.get("format_name"),
        }

    except Exception as e:
        logger.exception("[METADATA] Failed to extract metadata from %s: %s", file_path_or_url, e)
        return _empty_metadata()


def _empty_metadata() -> Dict[str, Any]:
    return {
        "durationSec": 0.0,
        "durationMs": 0,
        "width": None,
        "height": None,
        "resolution": None,
        "fps": None,
        "videoCodec": None,
        "audioCodec": None,
        "audioSampleRate": None,
        "audioChannels": None,
        "fileSizeBytes": None,
        "bitrateKbps": None,
        "formatName": None,
    }
