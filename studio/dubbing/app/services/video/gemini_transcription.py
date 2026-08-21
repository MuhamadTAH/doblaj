import os
import json
import base64
import logging
import asyncio
import aiohttp
import subprocess
from pathlib import Path

from app.services.video import MAX_AUDIO_BYTES
from app.core.sanitizer import sanitize_transcript

logger = logging.getLogger(__name__)

async def _compress_audio_to_base64(wav_path: str) -> str:
    """Compresses WAV to 64kbps MP3 and returns base64."""
    mp3_path = wav_path.replace(".wav", ".mp3")
    try:
        subprocess.run([
            "ffmpeg", "-y", "-i", wav_path, "-acodec", "libmp3lame", "-ab", "64k", mp3_path
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

        # Pird: cap encoded audio size to bound memory + payload. See PIRD-021.
        with open(mp3_path, "rb") as f:
            raw = f.read()
        if len(raw) > MAX_AUDIO_BYTES:
            raise ValueError(f"audio too large: {len(raw)} bytes (max {MAX_AUDIO_BYTES})")
        encoded = base64.b64encode(raw).decode("utf-8")
        return encoded
    except Exception as e:
        logger.error(f"Compression failed for {wav_path}: {e}")
        return ""
    finally:
        if os.path.exists(mp3_path):
            try:
                os.remove(mp3_path)
            except:
                pass

async def transcribe_and_segment_gemini(chunks: list) -> list:
    """
    Takes a list of VAD chunks and transcribes them in batches of 5 via Gemini API.
    Uses Mega-Payload Prompting with Structural JSON enforcement.
    """
    # Pird: API key from env, fail closed in prod. The previous hardcoded key
    # has been removed and MUST be rotated in the GCP console immediately.
    API_KEY = os.getenv("GEMINI_API_KEY", "")
    if not API_KEY:
        if os.getenv("PIRD_ENV") == "prod":
            raise RuntimeError("GEMINI_API_KEY is not configured in production")
        logger.warning("[GEMINI STT] GEMINI_API_KEY not set. Returning empty transcriptions.")
        for chunk in chunks:
            chunk["kurdish_raw"] = ""
            if not chunk.get("speaker"):
                chunk["speaker"] = "A"
        return chunks
    # Pird: keep URL clean; API key goes in `x-goog-api-key` header so it
    # never lands in URL logs (proxies, browser history, telemetry). See
    # pass-7 review.
    # Pird: model name from env, default to gemini-3.5-flash. Operators can pin
    # a different model without editing source. See PIRD-020.
    _MODEL = os.getenv("GEMINI_STT_MODEL", "gemini-3.5-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{_MODEL}:generateContent"
    headers = {
        "x-goog-api-key": API_KEY,
        "Content-Type": "application/json",
    }
    
    # --- OLD OPENROUTER IMPLEMENTATION (DISABLED) ---
    # api_key = os.getenv("OPEN_ROUTER_API_KEY")
    # if not api_key:
    #     logger.warning("[GEMINI STT] OPEN_ROUTER_API_KEY not set. Returning empty transcriptions.")
    #     for chunk in chunks:
    #         chunk["kurdish_raw"] = ""
    #         if not chunk.get("speaker"): chunk["speaker"] = "A"
    #     return chunks
    # 
    # url = "https://openrouter.ai/api/v1/chat/completions"
    # headers = {
    #     "Authorization": f"Bearer {api_key}",
    #     "Content-Type": "application/json"
    # }

    chunks = sorted(chunks, key=lambda x: x.get("start", 0))
    
    BATCH_SIZE = 5
    previous_chunk_text = ""

    async with aiohttp.ClientSession() as session:
        for i in range(0, len(chunks), BATCH_SIZE):
            batch = chunks[i:i + BATCH_SIZE]
            
            content_array = []
            
            # Fail-Loud Strict JSON Schema (Confidence Scoring + Human Review Gate)
            fail_loud_schema = """{
  "transcriptions": {
    "<chunk_id>": {
      "kurdish_sorani": "exact Kurdish text",
      "confidence_score": 0.95,
      "overlap_unresolvable": false,
      "reasoning_if_unresolvable": ""
    }
  }
}"""
            master_prompt = (
                "You are an expert Kurdish Sorani (کوردی سۆرانی) transcriber. "
                "Transcribe the following audio chunks with high precision. "
                "CRITICAL: If an audio segment contains severe overlapping crosstalk or unintelligible speech that cannot be deciphered with high confidence, "
                "set 'overlap_unresolvable': true, set 'confidence_score' < 0.60, and state the reason in 'reasoning_if_unresolvable'. "
                "Do NOT guess or hallucinate. "
                f"Output strictly in this JSON format:\n{fail_loud_schema}"
            )
            
            if previous_chunk_text:
                master_prompt += f'\n\nPrior Context: The speaker previously said: "{previous_chunk_text}". Ensure grammatical and semantic continuity where applicable.'
                
            content_array.append({
                "text": master_prompt
            })
            
            for c in batch:
                chunk_id = c.get("chunk_id", f"chunk_{i}")
                audio_path = c.get("audio_file")
                
                b64_audio = ""
                if audio_path and os.path.exists(audio_path):
                    b64_audio = await _compress_audio_to_base64(audio_path)
                
                if b64_audio:
                    speaker_id = c.get("speaker", "Speaker_A")
                    duration = c.get("duration", c.get("duration_sec", 0.0))
                    turn_type = "Short Colloquial Interjection" if duration < 2.0 else "Continuous Dialogue"
                    content_array.append({
                        "text": f"Audio for {chunk_id} [Speaker: {speaker_id}, Duration: {duration:.2f}s, Turn: {turn_type}]:"
                    })
                    content_array.append({
                        "inline_data": {
                            "data": b64_audio,
                            "mime_type": "audio/mp3"
                        }
                    })
                else:
                    logger.warning(f"[GEMINI STT] Missing audio or compression failed for {chunk_id}.")

            payload = {
                "contents": [
                    {
                        "parts": content_array
                    }
                ],
                "generationConfig": {"response_mime_type": "application/json"}
            }

            try:
                async with session.post(url, json=payload, headers=headers, timeout=120) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if "candidates" in data and len(data["candidates"]) > 0:
                            content = data["candidates"][0]["content"]["parts"][0]["text"]
                        else:
                            content = ""
                        
                        try:
                            clean_content = content.strip()
                            if clean_content.startswith("```json"):
                                clean_content = clean_content[7:]
                            if clean_content.endswith("```"):
                                clean_content = clean_content[:-3]
                            clean_content = clean_content.strip()
                            
                            # Support both nested {"transcriptions": {...}} and flat {chunk_id: ...}
                            trans_dict = parsed_json.get("transcriptions", parsed_json)
                            for c in batch:
                                c_id = c.get("chunk_id")
                                item = trans_dict.get(c_id, "")
                                if isinstance(item, dict):
                                    text = sanitize_transcript(item.get("kurdish_sorani", item.get("text", "")))
                                    c["kurdish_raw"] = text
                                    c["confidence_score"] = float(item.get("confidence_score", 1.0))
                                    c["overlap_unresolvable"] = bool(item.get("overlap_unresolvable", False))
                                    c["reasoning_if_unresolvable"] = item.get("reasoning_if_unresolvable", "")
                                    if c["overlap_unresolvable"] or c["confidence_score"] < 0.60:
                                        logger.warning(
                                            f"[GEMINI STT LOUD-FAIL] Chunk {c_id} flagged unresolvable! "
                                            f"Confidence: {c['confidence_score']:.2f} | Reason: {c['reasoning_if_unresolvable']}"
                                        )
                                else:
                                    text = sanitize_transcript(str(item))
                                    c["kurdish_raw"] = text
                                    c["confidence_score"] = 1.0
                                    c["overlap_unresolvable"] = False

                                if text and not c.get("overlap_unresolvable"):
                                    previous_chunk_text = text
                        except Exception as e:
                            logger.error(f"[GEMINI STT] Failed to parse JSON response for batch {i}: {e}. Content: {content}")
                            for c in batch:
                                c["kurdish_raw"] = ""
                                c["confidence_score"] = 0.0
                                c["overlap_unresolvable"] = True
                    else:
                        error_text = await resp.text()
                        logger.error(f"[GEMINI STT] API error {resp.status} for batch {i}: {error_text}")
                        for c in batch: c["kurdish_raw"] = ""
            except Exception as e:
                logger.error(f"[GEMINI STT] Exception for batch {i}: {e}")
                for c in batch: c["kurdish_raw"] = ""

    return chunks
