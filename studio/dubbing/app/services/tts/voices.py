"""
Voices service: read voice catalog from Convex (was: Supabase `voices` table).

Catalog is stored in the Convex `ttsVoices` table (see
D:/Pird/studio/dubbing/dashboard-tts/convex/schema.ts). The Python adapter
queries it via the public Convex queries `voices:list`, `voices:getById`,
and `voices:getIntroBytes` (no auth required — path B: global reference
data shared across all workspaces).
"""
import asyncio
import logging
import os
from typing import Optional

from convex import ConvexClient

logger = logging.getLogger(__name__)

CONVEX_URL = os.getenv("CONVEX_URL", "http://127.0.0.1:3210")

_client: Optional[ConvexClient] = None


def _get_client() -> ConvexClient:
    global _client
    if _client is None:
        _client = ConvexClient(CONVEX_URL)
    return _client


def voices_available() -> bool:
    return True


def _convex_row_to_api(row: dict) -> dict:
    """Map a Convex `ttsVoices` row to the API shape consumed by the
    Voice Library UI (VoiceOut in tts_dashboard.py)."""
    return {
        "id": row.get("legacyId") or str(row.get("_id", "")),
        "name": row.get("name") or "Unnamed Voice",
        "language": row.get("language") or "ar",
        "gender": row.get("gender") or "neutral",
        "description": row.get("description") or "",
        "tags": list(row.get("tags") or []),
        "is_yours": False,
        "provider": row.get("provider"),
        "provider_checkpoint": row.get("providerVoiceId"),
        "status": "active" if row.get("active", True) else "inactive",
        "voice_type": "public",
    }


FALLBACK_VOICES: list[dict] = [
    {
        "id": "fish-295e8c43",
        "name": "Anwar",
        "language": "ar-IQ",
        "gender": "male",
        "description": "Warm Iraqi Arabic male narrator",
        "tags": ["arabic", "iq", "narrator"],
        "is_yours": False,
        "provider": "fish_audio",
        "provider_checkpoint": "295e8c434c03469198a02ed8650ed9c6",
        "status": "active",
        "voice_type": "public",
    },
    {
        "id": "fish-564ff4b2",
        "name": "Layla",
        "language": "ar-IQ",
        "gender": "female",
        "description": "Soft Iraqi Arabic female voice",
        "tags": ["arabic", "iq", "narrator"],
        "is_yours": False,
        "provider": "fish_audio",
        "provider_checkpoint": "564ff4b232d6427f91513321de5fb651",
        "status": "active",
        "voice_type": "public",
    },
    {
        "id": "fish-93edb401",
        "name": "Karwan",
        "language": "ckb",
        "gender": "male",
        "description": "Kurdish Sorani male narrator",
        "tags": ["kurdish", "sorani", "narrator"],
        "is_yours": False,
        "provider": "fish_audio",
        "provider_checkpoint": "93edb401ddf94e9a836a74f141be5258",
        "status": "active",
        "voice_type": "public",
    },
    {
        "id": "fish-18372167",
        "name": "Najla",
        "language": "ar-IQ",
        "gender": "female",
        "description": "Friendly Iraqi Arabic female",
        "tags": ["arabic", "iq", "friendly"],
        "is_yours": False,
        "provider": "fish_audio",
        "provider_checkpoint": "183721675c2045499e8de847f4488b32",
        "status": "active",
        "voice_type": "public",
    },
    {
        "id": "fish-ca39ec48",
        "name": "Hassan",
        "language": "ar-IQ",
        "gender": "male",
        "description": "Deep Iraqi Arabic male",
        "tags": ["arabic", "iq", "deep"],
        "is_yours": False,
        "provider": "fish_audio",
        "provider_checkpoint": "ca39ec4818f94e979bacb8dfb9c73a33",
        "status": "active",
        "voice_type": "public",
    },
    {
        "id": "fish-a381d0da",
        "name": "Huda",
        "language": "ar-IQ",
        "gender": "female",
        "description": "Calm Iraqi Arabic female",
        "tags": ["arabic", "iq", "calm"],
        "is_yours": False,
        "provider": "fish_audio",
        "provider_checkpoint": "a381d0da904d402d82d457788d1b90fe",
        "status": "active",
        "voice_type": "public",
    },
    {
        "id": "fish-535fff20",
        "name": "Shawkat",
        "language": "ar-IQ",
        "gender": "male",
        "description": "Energetic Iraqi Arabic male",
        "tags": ["arabic", "iq", "energetic"],
        "is_yours": False,
        "provider": "fish_audio",
        "provider_checkpoint": "535fff20b534436ba242e6b2a5a7588d",
        "status": "active",
        "voice_type": "public",
    },
    {
        "id": "fish-47aedfd4",
        "name": "Maryam",
        "language": "ar-IQ",
        "gender": "female",
        "description": "Professional Iraqi Arabic female",
        "tags": ["arabic", "iq", "professional"],
        "is_yours": False,
        "provider": "fish_audio",
        "provider_checkpoint": "47aedfd446b54e69ab3b8de1f228a454",
        "status": "active",
        "voice_type": "public",
    },
    {
        "id": "fish-97de37d3",
        "name": "Aram",
        "language": "ckb",
        "gender": "male",
        "description": "Kurdish Sorani male voice",
        "tags": ["kurdish", "sorani"],
        "is_yours": False,
        "provider": "fish_audio",
        "provider_checkpoint": "97de37d35791427b859be305d9138c51",
        "status": "active",
        "voice_type": "public",
    },
    {
        "id": "fish-b9884d77",
        "name": "Bana",
        "language": "ckb",
        "gender": "female",
        "description": "Kurdish Sorani female voice",
        "tags": ["kurdish", "sorani"],
        "is_yours": False,
        "provider": "fish_audio",
        "provider_checkpoint": "b9884d77122d40688628d2ae22b6c44c",
        "status": "active",
        "voice_type": "public",
    },
    {
        "id": "fish-df6b40b9",
        "name": "Chra",
        "language": "ar-IQ",
        "gender": "female",
        "description": "Young Iraqi Arabic female",
        "tags": ["arabic", "iq", "young"],
        "is_yours": False,
        "provider": "fish_audio",
        "provider_checkpoint": "df6b40b9b06345b9af70b4ffd9aac98d",
        "status": "active",
        "voice_type": "public",
    },
    {
        "id": "fish-8a8880cf",
        "name": "Avin",
        "language": "ckb",
        "gender": "female",
        "description": "Soft Kurdish Sorani female",
        "tags": ["kurdish", "sorani", "soft"],
        "is_yours": False,
        "provider": "fish_audio",
        "provider_checkpoint": "8a8880cf09d74f56beb05ae98f01f504",
        "status": "active",
        "voice_type": "public",
    },
]


async def fetch_voices(limit: int = 200) -> list[dict]:
    """Return all active voices from Convex, mapped to API shape.
    Falls back to built-in seed catalog if Convex is down or unseeded.
    """
    def _do():
        c = _get_client()
        rows = c.query("voices:list", {}) or []
        return [_convex_row_to_api(r) for r in rows[:limit]]
    try:
        results = await asyncio.to_thread(_do)
        if results:
            return results
    except Exception:
        logger.warning("[tts.voices] Convex fetch failed, using fallback voice catalog")
    return FALLBACK_VOICES[:limit]


async def get_voice_by_id(voice_id: str) -> Optional[dict]:
    """Fetch a single voice by legacyId (the seed convention is `fish-xxx`)."""
    def _do():
        c = _get_client()
        return c.query("voices:getById", {"id": voice_id})
    try:
        row = await asyncio.to_thread(_do)
        if row:
            return _convex_row_to_api(row)
    except Exception:
        logger.warning("[tts.voices] get_voice_by_id Convex failed for %s, checking fallback", voice_id)

    for v in FALLBACK_VOICES:
        if v["id"] == voice_id:
            return v
    return None


_intro_cache: dict[str, bytes] = {}


def cache_intro_audio(voice_id: str, audio_bytes: bytes) -> None:
    """Store audio bytes in memory for instant preview access."""
    if voice_id and audio_bytes:
        _intro_cache[voice_id] = audio_bytes


async def get_intro_audio(voice_id: str) -> Optional[bytes]:
    """Fetch the cached intro MP3 bytes for a voice, if any.

    Checks in-memory cache first (<1ms), then Convex database.
    Returns None if no cache exists (caller should fall back to live render
    via Fish Audio).
    """
    if voice_id in _intro_cache:
        return _intro_cache[voice_id]

    def _do() -> Optional[bytes]:
        c = _get_client()
        result = c.query("voices:getIntroBytes", {"id": voice_id})
        if not result:
            return None
        # Handle storage URL return shape
        url = result.get("url")
        if url:
            import urllib.request
            with urllib.request.urlopen(url) as resp:
                return resp.read()
        # Handle raw bytes array return shape
        if result.get("bytes"):
            return bytes(result["bytes"])
        return None

    try:
        audio_bytes = await asyncio.to_thread(_do)
        if audio_bytes:
            _intro_cache[voice_id] = audio_bytes
        return audio_bytes
    except Exception:
        logger.exception("[tts.voices] get_intro_audio failed for %s", voice_id)
        return None


async def ensure_intro_in_convex(voice_id: str) -> Optional[bytes]:
    """Trigger the Convex action to ensure the intro is rendered and stored permanently.
    Returns the audio bytes if successful.
    """
    internal_api_key = os.getenv("INTERNAL_API_KEY", "")
    if not internal_api_key:
        logger.warning("[tts.voices] INTERNAL_API_KEY not set; cannot call ensureIntroBackend")
        return None

    def _do():
        c = _get_client()
        row = c.query("voices:getById", {"id": voice_id})
        if not row or "_id" not in row:
            return None
        
        return c.action("voices:ensureIntroBackend", {
            "voiceRowId": row["_id"],
            "__internalApiKey": internal_api_key,
        })

    try:
        result = await asyncio.to_thread(_do)
        if result and result.get("storageId"):
            return await get_intro_audio(voice_id)
        return None
    except Exception:
        logger.exception("[tts.voices] ensure_intro_in_convex failed for %s", voice_id)
        return None
