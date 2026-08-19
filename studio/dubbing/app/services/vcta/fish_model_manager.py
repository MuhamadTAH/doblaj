import os
import logging
import asyncio
import aiohttp
from pathlib import Path
from typing import Dict, List, Optional, Any
import soundfile as sf
import numpy as np

logger = logging.getLogger("doblaj.vcta.fish_model_manager")


async def create_fish_audio_voice_model(audio_path: str, title: str = "doblaj_speaker") -> Optional[str]:
    """
    Uploads a 10-20s clean vocal sample to Fish Audio to create a dedicated, private
    fast-trained voice model (reference_id) for pristine speaker voice cloning.
    """
    api_key = os.getenv("FISH_SPEECH_API_KEY") or os.getenv("FISH_API_KEY")
    if not api_key:
        logger.warning("[FISH-MODEL] No FISH_SPEECH_API_KEY found. Skipping voice model creation.")
        return None

    if not os.path.exists(audio_path):
        logger.error(f"[FISH-MODEL] Speaker audio sample not found at: {audio_path}")
        return None

    url = "https://api.fish.audio/model"
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        data = aiohttp.FormData()
        data.add_field("visibility", "private")
        data.add_field("type", "tts")
        data.add_field("train_mode", "fast")
        data.add_field("title", title[:64])
        
        with open(audio_path, "rb") as f:
            audio_bytes = f.read()

        data.add_field(
            "voices",
            audio_bytes,
            filename="speaker_sample.wav",
            content_type="audio/wav"
        )

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, data=data, timeout=30) as resp:
                if resp.status in (200, 201):
                    res_json = await resp.json()
                    model_id = res_json.get("_id")
                    logger.info(f"✨ [FISH-MODEL] Successfully created Fish Audio Voice Model: {model_id} ('{title}')")
                    return model_id
                else:
                    err_txt = await resp.text()
                    logger.warning(f"[FISH-MODEL] Failed to create voice model (HTTP {resp.status}): {err_txt}")
                    return None
    except Exception as e:
        logger.warning(f"[FISH-MODEL] Error calling Fish Audio model creation API: {e}")
        return None


async def delete_fish_audio_voice_model(model_id: str) -> bool:
    """Deletes a temporary Fish Audio voice model after job completion to keep account clean."""
    if not model_id:
        return False

    api_key = os.getenv("FISH_SPEECH_API_KEY") or os.getenv("FISH_API_KEY")
    if not api_key:
        return False

    url = f"https://api.fish.audio/model/{model_id}"
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.delete(url, headers=headers, timeout=15) as resp:
                if resp.status in (200, 204):
                    logger.info(f"🗑️ [FISH-MODEL] Deleted temporary voice model: {model_id}")
                    return True
                else:
                    logger.debug(f"[FISH-MODEL] Notice deleting model {model_id}: status {resp.status}")
                    return False
    except Exception as e:
        logger.debug(f"[FISH-MODEL] Cleanup exception for model {model_id}: {e}")
        return False


def extract_speaker_reference_samples(
    vocals_stem_path: str,
    chunks: List[Dict[str, Any]],
    scratch_dir: Path
) -> Dict[str, str]:
    """
    Extracts the highest-quality 10-20 seconds of speech for each unique speaker
    in the video. Groups chunks by 'speaker_id' (or 'speaker' / 'speaker_label').
    Default single speaker is 'speaker_0'.
    
    Returns: { "speaker_0": "/path/to/clean_speaker_0.wav", ... }
    """
    if not os.path.exists(vocals_stem_path):
        return {}

    data, sr = sf.read(vocals_stem_path)
    if len(data.shape) > 1:
        data = data.mean(axis=1)

    # 1. Group chunks by speaker
    speaker_chunks: Dict[str, List[Dict[str, Any]]] = {}
    for c in chunks:
        spk = str(c.get("speaker_id") or c.get("speaker") or c.get("speaker_label") or "speaker_0").strip()
        if spk not in speaker_chunks:
            speaker_chunks[spk] = []
        speaker_chunks[spk].append(c)

    results: Dict[str, str] = {}

    for spk_id, spk_c_list in speaker_chunks.items():
        # Sort chunks by active speech duration descending (prioritize longest, clearest utterances)
        sorted_chunks = sorted(
            spk_c_list,
            key=lambda x: float(x.get("active_speech_duration_sec", x.get("duration_sec", 0.0))),
            reverse=True
        )

        collected_audio = []
        collected_dur = 0.0

        for c in sorted_chunks:
            s_sec = float(c.get("start_sec", 0.0))
            e_sec = float(c.get("end_sec", s_sec + c.get("duration_sec", 0.0)))
            lead_sil = float(c.get("lead_silence_sec", 0.0))
            tail_sil = float(c.get("tail_silence_sec", 0.0))

            # Trim leading/trailing silence to get pure voice
            speech_start = s_sec + lead_sil
            speech_end = max(speech_start + 0.5, e_sec - tail_sil)

            s_samp = max(0, int(speech_start * sr))
            e_samp = min(len(data), int(speech_end * sr))

            if e_samp > s_samp:
                segment = data[s_samp:e_samp]
                # Filter out near-silent segments
                rms = np.sqrt(np.mean(segment**2) + 1e-10)
                if rms > 0.015:
                    collected_audio.append(segment)
                    # Add tiny 50ms pause between concatenated sentences
                    collected_audio.append(np.zeros(int(0.05 * sr), dtype=np.float32))
                    collected_dur += (len(segment) / sr)

            if collected_dur >= 15.0:  # 15s is the optimal Fish Audio sweet spot
                break

        if collected_audio and collected_dur >= 2.0:
            full_spk_audio = np.concatenate(collected_audio)
        else:
            # Fallback to first 10 seconds of vocal stem
            anchor_len = min(len(data), int(10.0 * sr))
            full_spk_audio = data[:anchor_len]

        out_path = str(scratch_dir / f"clean_voice_reference_{spk_id}.wav")
        sf.write(out_path, full_spk_audio, sr)
        results[spk_id] = out_path
        logger.info(f"🎙️ [FISH-MODEL] Extracted {len(full_spk_audio)/sr:.2f}s clean speech reference for speaker '{spk_id}' -> {out_path}")

    return results
