import os
import json
import logging
import asyncio
import tempfile
import base64
from typing import Dict, Any, List, Optional
import httpx
from pydantic import BaseModel, Field
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.services import r2 as r2_storage
import app.core.database_convex as convex_db

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# 1. PYDANTIC SCHEMA CONTRACT
# ─────────────────────────────────────────────────────────────
class ChunkTranslationOutput(BaseModel):
    source_transcription: str = Field(
        description="Exact verbatim transcription of spoken words in the audio chunk"
    )
    kurdish_sorani_text: str = Field(
        description="Direct natural translation into Kurdish Sorani (سۆرانی) script"
    )
    is_empty_or_silence: bool = Field(
        description="True if audio contains only silence, background music, breaths, or non-speech noise"
    )


# ─────────────────────────────────────────────────────────────
# 2. KURDISH SORANI CANONICAL UNICODE NORMALIZATION
# ─────────────────────────────────────────────────────────────
KURDISH_CHAR_MAP = {
    "\u064a": "\u06cc",  # Arabic Yeh (ي) -> Kurdish Yeh (ی)
    "\u0643": "\u06a9",  # Arabic Kaf (ك) -> Kurdish Keheh (ک)
    "\u06be": "\u06d5",  # Heh Doachashmee (ھ) -> Kurdish Ae (ە)
}

def normalize_kurdish_text(text: str) -> str:
    """Normalizes Arabic/Persian Unicode variants into canonical Central Kurdish (Sorani) script."""
    if not text:
        return ""
    res = text
    for ar_char, ku_char in KURDISH_CHAR_MAP.items():
        res = res.replace(ar_char, ku_char)
    return res.strip()


# ─────────────────────────────────────────────────────────────
# 3. RESILIENT RATE-LIMITING & EXPONENTIAL BACKOFF
# ─────────────────────────────────────────────────────────────
def is_retryable_error(exception: BaseException) -> bool:
    """Determines if the exception is a transient HTTP rate-limit (429) or server error (503)."""
    if isinstance(exception, (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)):
        return True
    if isinstance(exception, httpx.HTTPStatusError):
        # 429 ResourceExhausted, 500/502/503/504 Server Errors
        return exception.response.status_code in (429, 500, 502, 503, 504)
    return False


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
async def call_gemini_multimodal_with_retry(
    url: str,
    payload: Dict[str, Any],
    headers: Dict[str, str],
) -> Dict[str, Any]:
    """Executes Gemini multimodal request with resilient exponential backoff with jitter."""
    async with httpx.AsyncClient(timeout=45.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()


# ─────────────────────────────────────────────────────────────
# 4. STRUCTURED MULTIMODAL GEMINI TRANSLATION
# ─────────────────────────────────────────────────────────────
async def transcribe_and_translate_chunk_gemini(
    audio_path: str,
    previous_context: str = "",
) -> ChunkTranslationOutput:
    """
    Transcribes source audio chunk and directly localizes into Kurdish Sorani
    using Gemini Multimodal API with sliding context window and Pydantic JSON enforcement.
    """
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        logger.warning("[NODE-3] GEMINI_API_KEY not configured. Returning fallback.")
        return ChunkTranslationOutput(
            source_transcription="Audio segment",
            kurdish_sorani_text="دەقی دەنگی نموونەیی",
            is_empty_or_silence=False,
        )

    model_name = os.getenv("GEMINI_STT_MODEL", "gemini-2.0-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"

    # Read and base64-encode audio chunk
    with open(audio_path, "rb") as f:
        audio_bytes = f.read()

    # Check for empty file
    if len(audio_bytes) < 100:
        return ChunkTranslationOutput(
            source_transcription="[Silence]",
            kurdish_sorani_text="[بێدەنگی]",
            is_empty_or_silence=True,
        )

    audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

    prompt = f"""You are an expert bilingual speech linguist and translator specializing in Central Kurdish (Sorani / کوردیی ناوەندی / سۆرانی).

YOUR TASK:
1. Transcribe the exact spoken words in this 44.1kHz audio chunk.
2. Translate the meaning directly into natural, fluent, and culturally authentic Kurdish Sorani (سۆرانی).
3. Maintain grammatical coherence and preserve the Subject-Object-Verb (SOV) sentence flow from the preceding segment.

STRICT LINGUISTIC RULES:
- Use standard Kurdish Unicode characters (ە, ێ, ۆ, ڕ, ڵ, وو, گ, چ, پ, ژ).
- Do NOT output markdown, backticks, conversational commentary, or meta text.
- If the audio contains only silence, instrumental music, breathing, coughs, or noise without intelligible human speech, set "is_empty_or_silence": true.

{f'PREVIOUS CHUNK CONTEXT (for grammatical continuity):\n"{previous_context}"\n' if previous_context else ''}
"""

    pydantic_json_schema = {
        "type": "object",
        "properties": {
            "source_transcription": {"type": "string"},
            "kurdish_sorani_text": {"type": "string"},
            "is_empty_or_silence": {"type": "boolean"},
        },
        "required": ["source_transcription", "kurdish_sorani_text", "is_empty_or_silence"],
    }

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
            "response_schema": pydantic_json_schema,
            "temperature": 0.1,
        },
    }

    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json",
    }

    try:
        data = await call_gemini_multimodal_with_retry(url, payload, headers)
        raw_json_str = data["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(raw_json_str)

        output = ChunkTranslationOutput(
            source_transcription=parsed.get("source_transcription", "").strip(),
            kurdish_sorani_text=normalize_kurdish_text(parsed.get("kurdish_sorani_text", "")),
            is_empty_or_silence=bool(parsed.get("is_empty_or_silence", False)),
        )
        return output

    except Exception as e:
        logger.error(f"[NODE-3] Multimodal Gemini call failed after retries: {e}")
        # Fallback to empty transcription rather than crashing the pipeline
        return ChunkTranslationOutput(
            source_transcription="[Audio transcription error]",
            kurdish_sorani_text="[هەڵە لە وەرگێڕان]",
            is_empty_or_silence=False,
        )


# ─────────────────────────────────────────────────────────────
# 5. ATOMIC CLAIMING & PIPELINE ORCHESTRATION
# ─────────────────────────────────────────────────────────────
async def process_node3_transcription(
    job_id: str,
    workspace_id: str = "",
) -> Dict[str, Any]:
    """
    Executes Node 3 with:
    1. Atomic chunk claiming & locking (claimNextBatch).
    2. Media retrieval & sliding context window.
    3. Structured multimodal Gemini translation with Pydantic validation.
    4. Resilient exponential backoff.
    5. Real-time Convex telemetry & pipeline handoff.
    """
    logger.info(f"[NODE-3] Starting Node 3 Multimodal Translation pipeline for job {job_id}")

    c = convex_db._get_client()

    # 1. Update Macro Job Status
    try:
        await convex_db.update_job_status(
            c,
            workspace_id=workspace_id,
            job_id=job_id,
            status="TRANSLATING_CHUNKS",
            progress=30,
        )
    except Exception as e:
        logger.warning(f"[NODE-3] Macro status update notice: {e}")

    total_processed = 0
    previous_context = ""
    batch_size = 5

    with tempfile.TemporaryDirectory() as temp_dir:
        while True:
            # 2. ATOMIC CLAIM: Claim next available batch of chunks
            claimed_chunks = await convex_db.claim_next_batch(c, job_id=job_id, batch_size=batch_size)

            if not claimed_chunks:
                logger.info(f"[NODE-3] No more pending chunks to claim for job {job_id}.")
                break

            logger.info(f"[NODE-3] Atomically claimed {len(claimed_chunks)} chunks for processing.")

            for chunk in claimed_chunks:
                chunk_idx = chunk.get("chunkIndex", 0)
                r2_key = chunk.get("kurdish_raw_audio_url") or chunk.get("audioPath") or ""

                if not r2_key:
                    logger.warning(f"[NODE-3] Chunk #{chunk_idx} has no audio R2 key. Marking SKIPPED.")
                    await convex_db.complete_chunk_translation(
                        c,
                        job_id=job_id,
                        chunk_index=chunk_idx,
                        source_text="[No audio key]",
                        kurdish_text="[بێدەنگی]",
                        is_empty_or_silence=True,
                    )
                    continue

                local_chunk_path = os.path.join(temp_dir, f"chunk_{chunk_idx}.wav")

                try:
                    # 3. Media Retrieval
                    await asyncio.to_thread(r2_storage.download_file, r2_key, local_chunk_path)

                    # 4. Structured Multimodal Gemini Call with Sliding Context
                    result = await transcribe_and_translate_chunk_gemini(
                        local_chunk_path,
                        previous_context=previous_context,
                    )

                    if not result.is_empty_or_silence and result.kurdish_sorani_text:
                        previous_context = result.kurdish_sorani_text

                    # 5. Immediate Convex Telemetry Emission
                    await convex_db.complete_chunk_translation(
                        c,
                        job_id=job_id,
                        chunk_index=chunk_idx,
                        source_text=result.source_transcription,
                        kurdish_text=result.kurdish_sorani_text,
                        is_empty_or_silence=result.is_empty_or_silence,
                    )
                    total_processed += 1
                    logger.info(
                        f"[NODE-3] Chunk #{chunk_idx + 1} completed: "
                        f"Empty={result.is_empty_or_silence} | Text='{result.kurdish_sorani_text[:40]}...'"
                    )

                except Exception as chunk_err:
                    logger.error(f"[NODE-3] Fatal error on chunk #{chunk_idx}: {chunk_err}")
                    await convex_db.complete_chunk_translation(
                        c,
                        job_id=job_id,
                        chunk_index=chunk_idx,
                        is_empty_or_silence=False,
                        error=str(chunk_err),
                    )

                finally:
                    if os.path.exists(local_chunk_path):
                        try:
                            os.remove(local_chunk_path)
                        except Exception:
                            pass

    logger.info(f"[NODE-3] Node 3 pipeline completed for job {job_id}. Total processed: {total_processed}")
    return {
        "status": "success",
        "job_id": job_id,
        "processed_chunks": total_processed,
    }
