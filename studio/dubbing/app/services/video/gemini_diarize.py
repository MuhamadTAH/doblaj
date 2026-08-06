import os
import json
import base64
import logging
import asyncio
import aiohttp
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

def _compress_audio_to_base64(wav_path: str) -> str:
    """Compresses WAV to 64kbps MP3 and returns base64."""
    mp3_path = wav_path.replace(".wav", ".mp3")
    try:
        subprocess.run([
            "ffmpeg", "-y", "-i", wav_path, "-acodec", "libmp3lame", "-ab", "64k", mp3_path
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        
        with open(mp3_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")
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

async def gemini_audio_diarize_and_translate_async(chunk_path: str) -> list[dict]:
    """
    Phase 5 Multimodal Audio Diarization using OpenRouter (Base64 MP3 Trick).
    Returns: [{"speaker": "A", "text": "..."}, {"speaker": "B", "text": "..."}]
    """
    api_key = os.getenv("OPEN_ROUTER_API_KEY")
    if not api_key:
        # Pird: fail closed in prod. See pass-5 review (matches pass-2 Fix 11).
        if os.getenv("PIRD_ENV") == "prod":
            raise RuntimeError("OPEN_ROUTER_API_KEY is not configured in production")
        logger.error("[GEMINI DIARIZE] OPEN_ROUTER_API_KEY not found in environment.")
        return []

    b64_audio = _compress_audio_to_base64(chunk_path)
    if not b64_audio:
        return []

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    prompt = (
        "Listen to this audio. Two people are speaking Kurdish Sorani, and one interrupts or follows the other. "
        "Find the exact millisecond where the first speaker stops speaking and the second speaker begins. "
        "Output ONLY a JSON object containing the Arabic translation of the first speaker, the Arabic translation of the second speaker, "
        "and the key 'cut_time_seconds' representing the exact boundary in seconds where the voice changes. "
        "Format both Arabic translations phrase by phrase using commas (،) and full stops (.) at natural boundaries to guide text-to-speech pacing. "
        "Example format: {'speaker_0_arabic': '...', 'speaker_1_arabic': '...', 'cut_time_seconds': 0.6}"
    )

    payload = {
        "model": "google/gemini-flash-1.5",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:audio/mp3;base64,{b64_audio}"
                        }
                    }
                ]
            }
        ],
        "response_format": {"type": "json_object"}
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            logger.info("[GEMINI DIARIZE] Calling Gemini 1.5 Pro via OpenRouter...")
            async with session.post(url, headers=headers, json=payload, timeout=60) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    content = data["choices"][0]["message"]["content"]
                    
                    # Clean markdown code blocks if any
                    content = content.strip()
                    if content.startswith("```json"):
                        content = content[7:]
                    if content.endswith("```"):
                        content = content[:-3]
                    content = content.strip()
                    
                    # Fix common Gemini JSON hallucination with extra braces
                    import re
                    # content = re.sub(r'\}\s*\}\s*\]$', '} ]', content) # Removed for object
                    
                    try:
                        result = json.loads(content)
                        if isinstance(result, dict) and "speakers" in result:
                            result = result["speakers"]
                        # if not isinstance(result, list): # Now we expect a dict
                        #     logger.error(f"[GEMINI DIARIZE] Expected JSON array, got: {type(result)}")
                        #     return []
                        return result
                    except json.JSONDecodeError as e:
                        logger.error(f"[GEMINI DIARIZE] JSON Decode Error: {e}\nContent: {content}")
                        return []
                else:
                    error_text = await resp.text()
                    logger.error(f"[GEMINI DIARIZE] OpenRouter API error {resp.status}: {error_text}")
                    return []
    except Exception as e:
        logger.error(f"[GEMINI DIARIZE] Inference error: {e}")
        return []

def gemini_audio_diarize_and_translate(chunk_path: str) -> list[dict]:
    """Synchronous wrapper for backwards compatibility with the test script."""
    return asyncio.run(gemini_audio_diarize_and_translate_async(chunk_path))
