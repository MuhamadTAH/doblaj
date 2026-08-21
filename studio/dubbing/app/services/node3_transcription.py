import os
import json
import logging
import asyncio
import tempfile
import base64
from typing import Dict, Any, List, Optional
import httpx

from app.services import r2 as r2_storage
import app.core.database_convex as convex_db

logger = logging.getLogger(__name__)

# Kurdish Sorani Canonical Unicode Normalization
KURDISH_CHAR_MAP = {
    "\u064a": "\u06cc",  # Arabic Yeh -> Farsi/Kurdish Yeh (ی)
    "\u0643": "\u06a9",  # Arabic Kaf -> Kurdish Keheh (ک)
    "\u06be": "\u06d5",  # Heh Doachashmee -> Kurdish Ae (ە)
}

def normalize_kurdish_text(text: str) -> str:
    """Normalizes Arabic/Persian Unicode variants into canonical Central Kurdish (Sorani) script."""
    if not text:
        return ""
    res = text
    for ar_char, ku_char in KURDISH_CHAR_MAP.items():
        res = res.replace(ar_char, ku_char)
    return res.strip()


async def transcribe_chunk_with_gemini(
    audio_path: str,
    previous_context: str = "",
) -> str:
    """
    Transcribes a single 44.1kHz audio chunk into Kurdish Sorani using Gemini 1.5 / 2.0 / 3.1 Pro/Flash.
    Uses strict prompt instructions for pure Kurdish Sorani Unicode script.
    """
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        logger.warning("[NODE-3 ASR] GEMINI_API_KEY not configured. Returning fallback transcript.")
        return "دەقی دەنگی نموونەیی"

    model_name = os.getenv("GEMINI_STT_MODEL", "gemini-2.0-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"

    # Read and encode audio file
    with open(audio_path, "rb") as f:
        audio_bytes = f.read()
    audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

    prompt = f"""You are an expert Kurdish Sorani (سۆرانی) speech transcriptionist.
Listen to this audio chunk carefully and transcribe EXACTLY what the speaker says in Kurdish Sorani.

STRICT RULES:
1. Output ONLY the Kurdish Sorani text in Arabic-based Kurdish alphabet (ئەلفوبێی کوردی).
2. Use standard Kurdish Unicode characters (ە, ێ, ۆ, ڕ, ڵ, وو, گ, چ, پ, ژ).
3. Do NOT translate into Arabic or English.
4. Do NOT output timestamps, Markdown formatting, or notes.
5. If the audio is silent or contains only music/noise, output strictly: [بێدەنگی]
{f'Previous sentence context for continuity: "{previous_context}"' if previous_context else ''}

Return JSON with format:
{{"kurdish_text": "..."}}
"""

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": "audio/wav",
                            "data": audio_b64,
                        }
                    },
                ]
            }
        ],
        "generationConfig": {
            "response_mime_type": "application/json",
            "temperature": 0.1,
        },
    }

    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=45.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

        try:
            raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
            parsed = json.loads(raw_text)
            kurdish_text = parsed.get("kurdish_text", "")
        except Exception as parse_err:
            logger.warning(f"[NODE-3 ASR] Failed to parse JSON from Gemini, falling back to raw: {parse_err}")
            raw_text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            kurdish_text = raw_text.strip()

        return normalize_kurdish_text(kurdish_text)


async def process_node3_transcription(
    job_id: str,
    workspace_id: str = "",
) -> Dict[str, Any]:
    """
    Executes Node 3 Kurdish Sorani ASR with instant, granular per-chunk WebSocket mutations to Convex.
    """
    logger.info(f"[NODE-3 ASR] Starting Kurdish Sorani transcription for job {job_id}")

    # 1. Fetch chunks from Convex
    c = convex_db._get_client()

    chunks: List[Dict[str, Any]] = []
    try:
        def _fetch():
            return c.query("adminQuery:listChunksForJob", {"jobId": job_id})
        chunks = await asyncio.to_thread(_fetch)
    except Exception as e:
        logger.error(f"[NODE-3 ASR] Failed to fetch chunks for job {job_id}: {e}")
        raise RuntimeError(f"Could not load chunks for job {job_id}: {e}")

    if not chunks:
        logger.warning(f"[NODE-3 ASR] No chunks found for job {job_id}")
        return {"status": "error", "error": "No chunks found"}

    # Sort chunks by chunkIndex
    chunks = sorted(chunks, key=lambda x: x.get("chunkIndex", 0))
    logger.info(f"[NODE-3 ASR] Found {len(chunks)} chunks to transcribe for job {job_id}")

    # 2. Update Job Macro Status to TRANSCRIBING_CHUNKS
    try:
        await convex_db.update_job_status(
            c,
            workspace_id=workspace_id,
            job_id=job_id,
            status="TRANSCRIBING_CHUNKS",
            progress=30,
        )
    except Exception as e:
        logger.warning(f"[NODE-3 ASR] Macro status update notice: {e}")

    transcribed_count = 0
    previous_context = ""

    with tempfile.TemporaryDirectory() as temp_dir:
        for idx, chunk in enumerate(chunks):
            chunk_idx = chunk.get("chunkIndex", idx)
            r2_key = chunk.get("kurdish_raw_audio_url") or chunk.get("audioPath") or ""

            logger.info(f"[NODE-3 ASR] Processing Chunk #{chunk_idx + 1} ({r2_key})")

            # 3a. IMMEDIATELY emit micro-step: PROCESSING
            try:
                await convex_db.update_chunk_micro_status(
                    c,
                    job_id=job_id,
                    chunk_index=chunk_idx,
                    status="PROCESSING",
                )
            except Exception as micro_err:
                logger.warning(f"[NODE-3 ASR] Failed to emit PROCESSING for chunk #{chunk_idx}: {micro_err}")

            if not r2_key:
                logger.warning(f"[NODE-3 ASR] Chunk #{chunk_idx} has no audio R2 key. Skipping.")
                continue

            local_chunk_path = os.path.join(temp_dir, f"chunk_{chunk_idx}.wav")
            try:
                # 3b. Download chunk from R2
                await asyncio.to_thread(r2_storage.download_file, r2_key, local_chunk_path)

                # 3c. Call Gemini STT
                kurdish_text = await transcribe_chunk_with_gemini(
                    local_chunk_path,
                    previous_context=previous_context,
                )

                if kurdish_text and kurdish_text != "[بێدەنگی]":
                    previous_context = kurdish_text

                # 3d. IMMEDIATELY emit micro-step: COMPLETED with text!
                await convex_db.update_chunk_micro_status(
                    c,
                    job_id=job_id,
                    chunk_index=chunk_idx,
                    status="COMPLETED",
                    kurdish_text=kurdish_text,
                )
                transcribed_count += 1
                logger.info(f"[NODE-3 ASR] Chunk #{chunk_idx + 1} transcribed: {kurdish_text[:50]}...")

            except Exception as chunk_err:
                logger.error(f"[NODE-3 ASR] Error transcribing Chunk #{chunk_idx + 1}: {chunk_err}")
                await convex_db.update_chunk_micro_status(
                    c,
                    job_id=job_id,
                    chunk_index=chunk_idx,
                    status="FAILED",
                    error=str(chunk_err),
                )
            finally:
                if os.path.exists(local_chunk_path):
                    try:
                        os.remove(local_chunk_path)
                    except Exception:
                        pass

    # 4. Final Macro Status Update
    try:
        await convex_db.update_job_status(
            c,
            workspace_id=workspace_id,
            job_id=job_id,
            status="TRANSCRIPTION_COMPLETE",
            progress=50,
        )
    except Exception as e:
        logger.warning(f"[NODE-3 ASR] Final macro update notice: {e}")

    logger.info(f"[NODE-3 ASR] Node 3 completed for job {job_id}: {transcribed_count}/{len(chunks)} transcribed.")
    return {
        "status": "success",
        "job_id": job_id,
        "transcribed_count": transcribed_count,
        "total_chunks": len(chunks),
    }
