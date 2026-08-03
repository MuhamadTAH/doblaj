"""
TTS Dashboard routes (merged from studio/tts-service_old/ per
D:\\pird\\handoffs\\dubbing-tts-merge-want-vs-have.md Fix 1+4).

Endpoints (all under prefix /api/tts-dashboard):
  GET  /health                -> liveness (unauthenticated)
  GET  /voices                -> list voices from Supabase (auth-gated)
  POST /tts                   -> proxy (or stub) -> Fish Audio TTS (auth-gated)
  GET  /voices/{id}/preview   -> short audio sample via Fish Audio (auth-gated)

Fix 4 auth: each browser-facing endpoint accepts EITHER a signed-in user
(via Supabase JWT in `dubbing_access_token` cookie OR `Authorization: Bearer`)
OR an internal service caller presenting `x-internal-key: $INTERNAL_API_KEY`.
This replaces the previous UA-sniffing helper which violated Rule 3
(anyone with curl + Mozilla UA bypassed auth).

The `health` endpoint stays unauthenticated — it's a liveness probe.
"""
import logging
import os
from typing import List, Optional, Literal

from fastapi import APIRouter, HTTPException, Request, Header, Depends
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel, Field

from app.auth.clerk_auth import require_user_optional, AuthenticatedUser
from app.services.tts import fish_audio, voices as voices_svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tts-dashboard", tags=["tts_dashboard"])

INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")


async def _auth_or_internal(
    request: Request,
    user: Optional[AuthenticatedUser] = Depends(require_user_optional),
) -> Optional[AuthenticatedUser]:
    """Accept either a valid Clerk user (cookie or Bearer) OR a matching
    `x-internal-key`. Raises 401 if neither is present. Returns the user
    when authenticated (so routes can scope by workspace later) or None
    when only the internal-key path matched.

    PIRD-022: fail-closed by default. If `INTERNAL_API_KEY` is unset AND
    `PIRD_ENV` is anything other than `prod` or `dev_explicit`, return
    401. Operators must explicitly opt into dev-open mode by setting
    `PIRD_ENV=dev_explicit`.
    """
    if user is not None:
        return user
    if not INTERNAL_API_KEY:
        env = os.getenv("PIRD_ENV", "").lower()
        if env == "prod":
            raise HTTPException(
                status_code=503,
                detail="INTERNAL_API_KEY is not configured on the server",
            )
        if env != "dev_explicit":
            # PIRD-022: do not silently return None. Refuse the request.
            raise HTTPException(
                status_code=401,
                detail=(
                    "INTERNAL_API_KEY is not configured and PIRD_ENV is not "
                    "'dev_explicit'. Set PIRD_ENV=dev_explicit to opt into "
                    "open dev mode."
                ),
            )
        logger.warning("[TTS-DASHBOARD] dev_explicit mode allows unauthenticated access")
        return None
    if request.headers.get("x-internal-key") == INTERNAL_API_KEY:
        return None
    raise HTTPException(
        status_code=401,
        detail="Unauthorized: sign in or send x-internal-key",
    )


# --- Pydantic models ---------------------------------------------------------

class VoiceOut(BaseModel):
    id: str
    name: str
    language: str
    gender: Literal["male", "female", "neutral"] = "neutral"
    description: str = ""
    tags: List[str] = []
    is_yours: bool = False
    provider: Optional[str] = None
    provider_checkpoint: Optional[str] = None
    status: Optional[str] = None
    voice_type: Optional[str] = None


class TtsBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    voice_id: str
    consent_text_version: str = Field(..., min_length=1)
    language: str = "ar-IQ"
    speed: float = Field(1.0, ge=0.5, le=2.0)
    pitch: int = 0
    format: Literal["mp3", "wav"] = "mp3"


# --- Endpoints ---------------------------------------------------------------

@router.get("/health")
async def health():
    return {
        "status": "ok",
        "fish_available": fish_audio.fish_available(),
        "voices_configured": voices_svc.voices_available(),
        "fish_model": fish_audio.FISH_TTS_MODEL,
        "stub_mode": not fish_audio.fish_available(),
    }


@router.get("/voices", response_model=List[VoiceOut])
async def list_voices(_user: Optional[AuthenticatedUser] = Depends(_auth_or_internal)):
    rows = await voices_svc.fetch_voices()
    return [VoiceOut(**r) for r in rows]


@router.post("/tts")
async def tts(
    body: TtsBody,
    request: Request,
    _user: Optional[AuthenticatedUser] = Depends(_auth_or_internal),
):
    voice = await voices_svc.get_voice_by_id(body.voice_id)
    if voice is None or not voice.get("provider_checkpoint"):
        raise HTTPException(status_code=404, detail="voice not found or missing checkpoint")

    # Consent Logging
    user_ip_address = request.headers.get("CF-Connecting-IP") or request.headers.get("X-Forwarded-For") or (request.client.host if request.client else "unknown")
    if "," in user_ip_address:
        user_ip_address = user_ip_address.split(",")[0].strip()

    user_id = _user.user_id if _user else "internal"
    workspace_id = _user.workspace_id if _user else "internal"

    import hashlib
    input_text_id = hashlib.sha256(body.text.encode("utf-8")).hexdigest()

    from app.core import database_convex
    await database_convex.log_consent(
        user_id=user_id,
        workspace_id=workspace_id,
        consent_version=body.consent_text_version,
        user_ip_address=user_ip_address,
        input_text_id=input_text_id
    )

    audio = await fish_audio.render_tts(
        body.text,
        voice["provider_checkpoint"],
        speed=body.speed,
        volume=body.pitch,
        fmt=body.format,
    )
    media_type = "audio/mpeg" if body.format == "mp3" else "audio/wav"
    return Response(
        content=audio,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="pird-tts.{body.format}"'},
    )


@router.get("/voices/{voice_id}/preview")
async def voice_preview(
    voice_id: str,
    _user: Optional[AuthenticatedUser] = Depends(_auth_or_internal),
):
    cache_headers = {
        "Content-Disposition": f'attachment; filename="preview-{voice_id}.mp3"',
        "Cache-Control": "public, max-age=86400, immutable",
    }

    # Pird: try in-memory / Convex-cached intro first (zero Fish credits, fast <1ms).
    cached = await voices_svc.get_intro_audio(voice_id)
    if cached:
        return Response(
            content=cached,
            media_type="audio/mpeg",
            headers=cache_headers,
        )

    voice = await voices_svc.get_voice_by_id(voice_id)
    if voice is None or not voice.get("provider_checkpoint"):
        raise HTTPException(status_code=404, detail="voice not found or missing checkpoint")

    # Fallback: ensure generated and stored in Convex permanently
    audio = await voices_svc.ensure_intro_in_convex(voice_id)

    # Secondary Fallback: live render via Fish Audio if Convex action fails
    if not audio:
        audio = await fish_audio.render_tts(
            text="صوت علامتك التجارية هو هويتك. نحن نضمن لك دبلجة احترافية، سلسة، وطبيعية، لنوصل رسالتك إلى الجمهور العربي بأعلى درجات الدقة والتأثير.",
            voice_checkpoint=voice["provider_checkpoint"],
            speed=1.0,
            volume=0,
            fmt="mp3",
        )
        # Save to memory cache so subsequent requests for this voice are instant
        if audio:
            voices_svc.cache_intro_audio(voice_id, audio)

    return Response(
        content=audio,
        media_type="audio/mpeg",
        headers=cache_headers,
    )
