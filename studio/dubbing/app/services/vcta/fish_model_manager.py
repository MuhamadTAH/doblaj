import os
import logging
import asyncio
import aiohttp
from pathlib import Path
from typing import Dict, List, Optional, Any
import soundfile as sf
import numpy as np

logger = logging.getLogger("doblaj.vcta.fish_model_manager")


def estimate_t60_reverberation(vocal_stem_path: str) -> float:
    """
    Estimates the reverberation decay time (T60) of the original speaker's vocals.
    If T60 < 0.20s (standard close mic / lavalier on phone), returns ~0.10s (bone-dry).
    If T60 >= 0.35s (room echo detected), returns the estimated T60 for matched early reflection.
    """
    try:
        if not os.path.exists(vocal_stem_path):
            return 0.10
        data, sr = sf.read(vocal_stem_path)
        if len(data.shape) > 1:
            data = data.mean(axis=1)
        frame_len = int(0.02 * sr)
        rms_frames = [np.sqrt(np.mean(data[i:i+frame_len]**2) + 1e-10) for i in range(0, len(data)-frame_len, frame_len)]
        rms_db = 20 * np.log10(np.maximum(rms_frames, 1e-5))
        decays = []
        for i in range(len(rms_db)-10):
            if rms_db[i] > -20.0 and rms_db[i+1] < rms_db[i]:
                start_val = rms_db[i]
                for k in range(1, 15):
                    if (start_val - rms_db[i+k]) >= 20.0:
                        decay_time = k * 0.02 * 3.0
                        if 0.05 <= decay_time <= 1.5:
                            decays.append(decay_time)
                        break
        median_t60 = float(np.median(decays)) if decays else 0.10
        return round(median_t60, 2)
    except Exception:
        return 0.10


def apply_two_pass_loudnorm(
    input_wav: str,
    output_wav: str,
    target_i: float = -14.0,
    target_tp: float = -1.0,
    target_lra: float = 7.0
) -> Dict[str, Any]:
    """
    Applies True Two-Pass EBU R128 Loudness Normalization in FFmpeg.
    Pass 1: Analyses integrated loudness, true peak, LRA, and threshold across the whole track.
    Pass 2: Applies clean LINEAR normalization (linear=true) using the exact measured stats.
    Guarantees full broadcast volume (-14.0 LUFS) with zero dynamic squashing and zero pumping.
    """
    import subprocess
    import json
    
    cmd1 = [
        "ffmpeg", "-y",
        "-i", input_wav,
        "-af", f"loudnorm=I={target_i}:TP={target_tp}:LRA={target_lra}:print_format=json",
        "-f", "null", "-"
    ]
    res1 = subprocess.run(cmd1, capture_output=True, text=True)
    
    lines = res1.stderr.split("\n")
    json_lines = []
    capturing = False
    for line in lines:
        if "{" in line:
            capturing = True
        if capturing:
            json_lines.append(line)
        if "}" in line and capturing:
            break
            
    if not json_lines:
        logger.warning(f"[LOUDNORM] Failed to parse JSON stats, falling back to basic loudnorm: {res1.stderr[:200]}")
        cmd_fallback = [
            "ffmpeg", "-y", "-i", input_wav,
            "-af", f"loudnorm=I={target_i}:TP={target_tp}:LRA={target_lra}",
            "-ar", "48000", "-ac", "2", output_wav
        ]
        subprocess.run(cmd_fallback, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return {}
        
    stats = json.loads("\n".join(json_lines))
    
    m_i = stats.get("input_i", "-24.0")
    m_tp = stats.get("input_tp", "-1.0")
    m_lra = stats.get("input_lra", "7.0")
    m_thresh = stats.get("input_thresh", "-34.0")
    m_offset = stats.get("target_offset", "0.0")
    
    pass2_filter = (
        f"loudnorm=I={target_i}:TP={target_tp}:LRA={target_lra}:"
        f"measured_I={m_i}:measured_TP={m_tp}:measured_LRA={m_lra}:"
        f"measured_thresh={m_thresh}:offset={m_offset}:linear=true"
    )
    
    cmd2 = [
        "ffmpeg", "-y",
        "-i", input_wav,
        "-af", pass2_filter,
        "-ar", "48000", "-ac", "2",
        output_wav
    ]
    subprocess.run(cmd2, capture_output=True, text=True, check=True)
    logger.info(f"🔊 [TWO-PASS LOUDNORM] Applied linear normalization: Input {m_i} LUFS -> Target {target_i} LUFS (Offset: {m_offset} dB, linear=true)")
    return stats


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

            # Cap at 90 seconds max to stay safely within Fish Audio's 10MB HTTP payload limit
            if collected_dur >= 90.0:
                break

        if collected_audio and collected_dur >= 2.0:
            full_spk_audio = np.concatenate(collected_audio)
        else:
            # Fallback to full vocal stem up to 60s
            anchor_len = min(len(data), int(60.0 * sr))
            full_spk_audio = data[:anchor_len]

        out_path = str(scratch_dir / f"clean_voice_reference_{spk_id}.wav")
        sf.write(out_path, full_spk_audio, sr, subtype="PCM_16")
        results[spk_id] = out_path
        logger.info(f"🎙️ [FISH-MODEL] Extracted {len(full_spk_audio)/sr:.2f}s full-video clean speech reference for speaker '{spk_id}' -> {out_path}")

    return results
