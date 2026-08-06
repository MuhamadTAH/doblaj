import os
import json
import logging
import asyncio
import aiohttp
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Pird: cap reference audio at Fish Audio's documented limit. See
# handoffs/dubbing-security-pass3-fixes.md Fix 2.
MAX_REFERENCE_AUDIO_BYTES = 10 * 1024 * 1024  # 10 MB

def _trim_reference_audio(input_wav: str, output_wav: str, speech_duration: float) -> str:
    """
    If a chunk was heavily padded with silence (ratio < 0.5), we trim it 
    to just the speech duration so silence doesn't pollute the TTS voice cloning.
    """
    try:
        subprocess.run([
            "ffmpeg", "-y", "-i", input_wav, "-t", str(speech_duration), 
            "-ar", "16000", "-ac", "1", output_wav
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return output_wav
    except Exception as e:
        logger.error(f"Failed to trim reference audio {input_wav}: {e}")
        return input_wav

async def _get_audio_duration(audio_path: str) -> float:
    """Returns the duration of an audio file in seconds using ffprobe."""
    # Pird: offload sync subprocess off the event loop. See
    # handoffs/dubbing-security-pass3-fixes.md Fix 6.
    def _run():
        return subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                audio_path,
            ],
            capture_output=True, text=True, check=True,
        )
    try:
        result = await asyncio.to_thread(_run)
        return float(result.stdout.strip())
    except Exception as e:
        logger.error(f"Failed to get audio duration for {audio_path}: {e}")
        return 0.0

async def _call_fish_speech(
    text: str,
    reference_audio_path: str,
    output_wav: str,
    chunk_id: str = "",
    reference_id: str | None = None,
    trace_retries: list | None = None,
    speed: float = 1.0
) -> tuple[bool, str]:
    """
    Calls the Fish Speech API (speech-1.6) for voice cloning.
    Handles msgpack body with audio bytes and retry logic.
    """
    api_key = os.getenv("FISH_SPEECH_API_KEY") or os.getenv("FISH_API_KEY")
    if not api_key:
        logger.error("[TTS] Neither FISH_SPEECH_API_KEY nor FISH_API_KEY is set in environment.")
        return False, "Neither FISH_SPEECH_API_KEY nor FISH_API_KEY environment variable is set"

    if not reference_id and not os.path.exists(reference_audio_path):
        logger.error(f"[TTS] Reference audio not found: {reference_audio_path}")
        return False, f"Reference audio not found: {reference_audio_path}"

    url = "https://api.fish.audio/v1/tts"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/msgpack"
    }
    
    import msgpack
    if reference_id:
        # Library voice mode — use the voice ID directly, no audio bytes
        payload = {
            "text": text,
            "reference_id": reference_id,
            "format": "wav",
            "model": "s2-pro",
            "prosody": {"speed": speed}
        }
    else:
        # Clone mode — send audio bytes
        # Pird: cap the reference audio at Fish Audio's limit and offload the
        # read off the event loop. See handoffs/dubbing-security-pass3-fixes.md Fix 2.
        ref_path = Path(reference_audio_path)
        if not ref_path.exists():
            raise FileNotFoundError(f"reference audio not found: {reference_audio_path}")
            
        size = ref_path.stat().st_size
        if size > MAX_REFERENCE_AUDIO_BYTES:
            raise ValueError(
                f"reference audio too large: {size} bytes (max {MAX_REFERENCE_AUDIO_BYTES})"
            )
        audio_bytes = await asyncio.to_thread(ref_path.read_bytes)
        payload = {
            "text": text,
            "references": [{"audio": audio_bytes, "text": ""}],
            "format": "wav",
            "model": "s2-pro",
            "prosody": {"speed": speed}
        }
    packed_payload = msgpack.packb(payload)

    # 4 attempts total (3 retries with backoff 1s, 2s, 4s)
    delays = [1, 2, 4]
    
    for attempt in range(4):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, data=packed_payload, timeout=60) as resp:
                    if trace_retries is not None:
                        trace_retries.append({"attempt": attempt + 1, "status": resp.status})
                    if resp.status == 200:
                        content = await resp.read()
                        # Pird: offload the response write off the event loop.
                        # See handoffs/dubbing-security-pass3-fixes.md Fix 12.
                        await asyncio.to_thread(Path(output_wav).write_bytes, content)
                        logger.info(f"[TTS] Fish Speech success for chunk {chunk_id}")
                        return True, ""
                    else:
                        error_body = await resp.text()
                        logger.error(f"[TTS] Fish Speech failed for chunk {chunk_id} with status {resp.status}. Body: {error_body}")
                        if resp.status in [429, 502, 503] and attempt < 3:
                            await asyncio.sleep(delays[attempt])
                            continue
                        return False, f"HTTP {resp.status}: {error_body}"
        except asyncio.TimeoutError:
            if attempt < 3:
                await asyncio.sleep(delays[attempt])
                continue
            return False, "Timeout Error: Fish Audio took too long to respond."
        except Exception as e:
            logger.error(f"[TTS] Fish Speech error for chunk {chunk_id}: {e}")
            return False, f"Exception: {str(e)}"
            
    return False, "Max retries reached."

async def generate_tts(text: str, reference_audio_path: str, output_wav: str, is_padded: bool = False, speech_duration: float = 0.0, speed: float = 1.0) -> tuple[bool, str]:
    """
    Public entry point for TTS generation. Handles padded audio trimming and enforces Fish Audio 10s limit.
    """
    target_ref = reference_audio_path or ""

    duration = 0.0
    if target_ref:
        import librosa
        try:
            duration = librosa.get_duration(filename=target_ref)
        except Exception:
            duration = 0.0

    # Fish Audio strictly rejects reference audio > 10 seconds.
    # Trim to 9.5s max, or the requested speech_duration if it's shorter.
    trim_target = min(9.5, speech_duration if speech_duration > 0 else 9.5)
    
    if target_ref and ((is_padded and speech_duration > 0) or duration > 9.9):
        trimmed = target_ref.replace(".wav", "_trimmed.wav")
        _trim_reference_audio(target_ref, trimmed, trim_target)
        target_ref = trimmed
        
    return await _call_fish_speech(text, target_ref, output_wav, speed=speed)
