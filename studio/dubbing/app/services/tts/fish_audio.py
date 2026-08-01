"""
Fish Audio TTS client (lightweight wrapper).

Merged from studio/tts-service_old/dashboard_api.py per
D:\\pird\\handoffs\\dubbing-tts-merge-want-vs-have.md Fix 1.

Behavior:
  - When FISH_API_KEY is missing OR TTS_FISH_STUB=true, returns a small
    silent WAV blob (length proportional to text). This lets the merge
    ship independently of the real Fish Audio key.
  - Otherwise calls Fish Audio's POST /v1/tts with the official
    request schema (https://docs.fish.audio/api-reference/endpoint/openapi-v1/text-to-speech).

Pure async function — no FastAPI deps. Route layer handles response shape.
"""
import os
import logging
from typing import Optional, Literal

import httpx

logger = logging.getLogger(__name__)

FISH_API_KEY = os.getenv("FISH_API_KEY", "") or os.getenv("FISH_SPEECH_API_KEY", "")
FISH_API_URL = "https://api.fish.audio/v1/tts"
FISH_TTS_MODEL = os.getenv("FISH_TTS_MODEL", "s2-pro")  # "s1" | "s2-pro"

# Pird: when True (or when FISH_API_KEY is empty), bypass Fish entirely
# and return a silent WAV. Useful for local dev and merge rollouts before
# the real key lands in .env.
TTS_FISH_STUB = os.getenv("TTS_FISH_STUB", "").lower() in ("1", "true", "yes")


def fish_available() -> bool:
    return bool(FISH_API_KEY) and not TTS_FISH_STUB


def make_silent_wav(seconds: float = 1.0, sample_rate: int = 8000) -> bytes:
    """Build a minimal valid silent WAV (mono 16-bit PCM)."""
    num_samples = max(1, int(seconds * sample_rate))
    buf = bytearray(44 + num_samples * 2)
    # RIFF header
    buf[0:4] = b"RIFF"
    buf[4:8] = (36 + num_samples * 2).to_bytes(4, "little")
    buf[8:12] = b"WAVE"
    # fmt chunk
    buf[12:16] = b"fmt "
    buf[16:20] = (16).to_bytes(4, "little")
    buf[20:22] = (1).to_bytes(2, "little")        # PCM
    buf[22:24] = (1).to_bytes(2, "little")        # mono
    buf[24:28] = sample_rate.to_bytes(4, "little")
    buf[28:32] = (sample_rate * 2).to_bytes(4, "little")  # byte rate
    buf[32:34] = (2).to_bytes(2, "little")        # block align
    buf[34:36] = (16).to_bytes(2, "little")       # bits/sample
    # data chunk
    buf[36:40] = b"data"
    buf[40:44] = (num_samples * 2).to_bytes(4, "little")
    # PCM samples left as 0 -> silence
    return bytes(buf)


async def render_tts(
    text: str,
    voice_checkpoint: str,
    *,
    model: Optional[str] = None,
    speed: float = 1.0,
    volume: int = 0,
    fmt: Literal["mp3", "wav"] = "mp3",
) -> bytes:
    """Render one TTS sample. Returns raw audio bytes (mp3 or wav).

    `voice_checkpoint` is the Fish Audio public-model ID (or any custom
    model ID the user has access to). When fish_available() is False,
    returns a silent WAV placeholder sized to the text length.
    """
    if not text.strip():
        # Empty input: 0.25s of silence so the browser doesn't choke on
        # a degenerate 0-byte payload.
        return make_silent_wav(0.25)

    if not fish_available():
        # Length scales with text so the UI feels real even with stub data.
        seconds = max(1.0, min(8.0, len(text) / 20.0))
        return make_silent_wav(seconds)

    payload = {
        "text": text,
        "reference_id": voice_checkpoint,
        "format": fmt,
        "prosody": {"speed": float(speed), "volume": int(volume)},
    }
    headers = {
        "Authorization": f"Bearer {FISH_API_KEY}",
        "Content-Type": "application/json",
        "model": model or FISH_TTS_MODEL,
    }

    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(FISH_API_URL, headers=headers, json=payload)
        if r.status_code != 200:
            # Fall through to stub so the UI doesn't break, but log loud.
            logger.warning(
                "Fish Audio TTS failed (%s): %s — falling back to silent stub",
                r.status_code, r.text[:200],
            )
            return make_silent_wav(max(1.0, min(8.0, len(text) / 20.0)))
        return r.content
