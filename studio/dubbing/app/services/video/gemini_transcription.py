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
            
            # The Master Prompt Reinforcement
            master_prompt = "You are an expert Kurdish Sorani transcriber. Transcribe the following audio chunks exactly as spoken in Kurdish Sorani. Do not translate them. Ensure grammatical continuity between the chunks. Output a strict JSON object mapping the chunk ID to its transcription. Do not skip any chunks."
            
            if previous_chunk_text:
                master_prompt += f'\n\nThe speaker previously said: "{previous_chunk_text}". Here is the next sequence of chunks. Transcribe them so the Kurdish Sorani grammar perfectly flows from the previous sentence.'
                
            content_array.append({
                "text": master_prompt
            })
            
            expected_keys = []
            
            for c in batch:
                chunk_id = c.get("chunk_id", f"chunk_{i}")
                expected_keys.append(chunk_id)
                audio_path = c.get("audio_file")
                
                b64_audio = ""
                if audio_path and os.path.exists(audio_path):
                    b64_audio = await _compress_audio_to_base64(audio_path)
                
                if b64_audio:
                    content_array.append({"text": f"Here is {chunk_id}:"})
                    content_array.append({
                        "inline_data": {
                            "data": b64_audio,
                            "mime_type": "audio/mp3"
                        }
                    })
                else:
                    logger.warning(f"[GEMINI STT] Missing audio or compression failed for {chunk_id}.")

            # Add the JSON format enforcement text
            json_format_str = ', '.join([f'"{k}": "text"' for k in expected_keys])
            content_array.append({
                "text": f"Output exactly in this JSON format and do not skip any chunks: {{{json_format_str}}}"
            })

            payload = {
                "contents": [
                    {
                        "parts": content_array
                    }
                ],
                # The response_format parameter works differently on the direct API,
                # but we can rely on the prompt instructing it to output JSON.
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
                            
                            try:
                                parsed_json = json.loads(clean_content)
                            except json.JSONDecodeError:
                                # Fallback: append closing brace if it was cut off
                                if not clean_content.endswith("}"):
                                    parsed_json = json.loads(clean_content + "}")
                                else:
                                    raise
                                    
                            for c in batch:
                                c_id = c.get("chunk_id")
                                text = sanitize_transcript(parsed_json.get(c_id, ""))
                                c["kurdish_raw"] = text
                                if text:
                                    previous_chunk_text = text # Track the last chunk's text for overlap
                        except Exception as e:
                            logger.error(f"[GEMINI STT] Failed to parse JSON response for batch {i}: {e}. Content: {content}")
                            for c in batch:
                                c["kurdish_raw"] = ""
                    else:
                        error_text = await resp.text()
                        logger.error(f"[GEMINI STT] API error {resp.status} for batch {i}: {error_text}")
                        for c in batch: c["kurdish_raw"] = ""
            except Exception as e:
                logger.error(f"[GEMINI STT] Exception for batch {i}: {e}")
                for c in batch: c["kurdish_raw"] = ""

    return chunks
