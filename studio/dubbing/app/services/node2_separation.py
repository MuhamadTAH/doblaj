"""
Node 2: Audio Separation & Segmentation Service
Zero-download headless audio extraction + Demucs htdemucs isolation + Silero VAD dual-fidelity segmentation.
Hardened for production with OOM guards, comprehensive diagnostics, and explicit Convex status reporting.
"""
from __future__ import annotations

import asyncio
import gc
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import soundfile as sf
import torch

from app.core import database_convex as convex_db
from app.services import r2

logger = logging.getLogger(__name__)

# Cache Silero VAD model globally in worker process
_SILERO_MODEL = None
_SILERO_UTILS = None


def get_silero_vad():
    global _SILERO_MODEL, _SILERO_UTILS
    if _SILERO_MODEL is None:
        logger.info("[NODE-2] Loading Silero VAD model into memory...")
        try:
            from silero_vad import load_silero_vad, read_audio, get_speech_timestamps
            model = load_silero_vad()
            utils = (get_speech_timestamps, None, read_audio)
            _SILERO_MODEL = model
            _SILERO_UTILS = utils
            logger.info("[NODE-2] Loaded Silero VAD from silero_vad package")
        except Exception as e:
            logger.info("[NODE-2] Falling back to torch.hub.load with trust_repo=True: %s", e)
            model, utils = torch.hub.load(
                repo_or_dir="snakers4/silero-vad",
                model="silero_vad",
                force_reload=False,
                onnx=False,
                trust_repo=True,
            )
            _SILERO_MODEL = model
            _SILERO_UTILS = utils
    return _SILERO_MODEL, _SILERO_UTILS


def extract_44k_audio_from_url(r2_signed_url: str, output_wav_path: str) -> None:
    """
    Step 1: Headless FFmpeg Extraction.
    Streams audio directly from the remote R2 URL over HTTP without downloading the video.
    Outputs standardized 44.1kHz stereo 16-bit PCM WAV (native Demucs training spec).
    """
    ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
    cmd = [
        ffmpeg_bin,
        "-y",
        "-i", r2_signed_url,
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "44100",
        "-ac", "2",
        output_wav_path,
    ]
    logger.info("[NODE-2][STEP 1] Running FFmpeg audio extraction to %s...", output_wav_path)
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if proc.returncode != 0:
        err_msg = proc.stderr.decode("utf-8", errors="ignore")
        logger.error("[NODE-2][STEP 1] FFmpeg extraction failed: %s", err_msg)
        raise RuntimeError(f"FFmpeg extraction failed (code {proc.returncode}): {err_msg[:400]}")

    if not os.path.exists(output_wav_path) or os.path.getsize(output_wav_path) < 100:
        raise RuntimeError(f"FFmpeg produced empty audio file at {output_wav_path}")

    dur = sf.info(output_wav_path).duration
    logger.info("[NODE-2][STEP 1] Audio extracted successfully! Duration: %.2fs, Size: %.2f MB", dur, os.path.getsize(output_wav_path) / (1024 * 1024))


def run_demucs_isolation(input_audio_path: str, output_dir: str) -> Tuple[str, str]:
    """
    Step 2: Demucs Vocal Isolation.
    Runs Hybrid Transformer Demucs (htdemucs) in --two-stems=vocals mode.
    Includes --segment 10 to prevent OOM on longer files.
    """
    device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info("[NODE-2][STEP 2] Running Demucs (htdemucs) on device=%s with segment=10 OOM protection...", device)

    # Use python -m demucs.separate or demucs binary
    cmd = [
        sys.executable,
        "-m", "demucs.separate",
        "--two-stems=vocals",
        "-n", "htdemucs",
        "--segment", "7",
        "-d", device,
        "-o", output_dir,
        input_audio_path,
    ]

    logger.info("[NODE-2][STEP 2] Executing Demucs: %s", " ".join(cmd))
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if proc.returncode != 0:
        err_msg = proc.stderr.decode("utf-8", errors="ignore")
        logger.error("[NODE-2][STEP 2] Demucs separation failed: %s", err_msg)
        raise RuntimeError(f"Demucs separation failed (code {proc.returncode}): {err_msg[:400]}")

    track_name = Path(input_audio_path).stem
    demucs_track_dir = Path(output_dir) / "htdemucs" / track_name
    vocals_path = demucs_track_dir / "vocals.wav"
    no_vocals_path = demucs_track_dir / "no_vocals.wav"

    if not vocals_path.is_file() or not no_vocals_path.is_file():
        # Search anywhere in output_dir for vocals.wav and no_vocals.wav
        found_vocals = list(Path(output_dir).glob("**/vocals.wav"))
        found_no_vocals = list(Path(output_dir).glob("**/no_vocals.wav"))
        if found_vocals and found_no_vocals:
            vocals_path = found_vocals[0]
            no_vocals_path = found_no_vocals[0]
        else:
            raise FileNotFoundError(f"Demucs output stems not found in {output_dir}")

    logger.info("[NODE-2][STEP 2] Demucs vocal isolation complete! Stems at %s", demucs_track_dir)
    return str(vocals_path), str(no_vocals_path)


def resample_to_16k_mono(input_wav_path: str, output_wav_path: str) -> None:
    """Resample 44.1kHz stereo audio to 16kHz mono specifically for Silero VAD."""
    ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
    cmd = [
        ffmpeg_bin,
        "-y",
        "-i", input_wav_path,
        "-ar", "16000",
        "-ac", "1",
        output_wav_path,
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"Resampling to 16k mono failed: {proc.stderr.decode('utf-8', errors='ignore')}")


def get_speech_segments_silero(wav_16k_mono_path: str, min_speech_duration_ms: int = 250) -> List[Dict[str, float]]:
    """
    Step 3: Silero VAD Resampling & Speech Boundary Detection.
    Returns list of speech segments: [{'start': 0.5, 'end': 4.2}, ...]
    """
    logger.info("[NODE-2][STEP 3] Running Silero VAD speech boundary detection...")
    model, (get_speech_ts, _, read_audio, *_) = get_silero_vad()
    wav_tensor = read_audio(wav_16k_mono_path, sampling_rate=16000)
    speech_timestamps = get_speech_ts(
        wav_tensor,
        model,
        sampling_rate=16000,
        min_speech_duration_ms=min_speech_duration_ms,
        min_silence_duration_ms=400,
        speech_pad_ms=200,
    )

    segments: List[Dict[str, float]] = []
    for ts in speech_timestamps:
        start_sec = round(ts["start"] / 16000.0, 3)
        end_sec = round(ts["end"] / 16000.0, 3)
        if end_sec - start_sec >= 0.3:
            segments.append({"start": start_sec, "end": end_sec})

    if not segments:
        data, sr = sf.read(wav_16k_mono_path)
        dur = round(len(data) / float(sr), 3)
        logger.warning("[NODE-2][STEP 3] No distinct speech boundaries detected by VAD. Using single whole segment (0.0s - %.2fs)", dur)
        segments = [{"start": 0.0, "end": dur}]

    # Merge adjacent pauses (< 0.6s) and cap chunk length at 12.0s
    merged: List[Dict[str, float]] = []
    curr = segments[0]
    for nxt in segments[1:]:
        gap = nxt["start"] - curr["end"]
        potential_len = nxt["end"] - curr["start"]
        if gap < 0.6 and potential_len <= 12.0:
            curr["end"] = nxt["end"]
        else:
            merged.append(curr)
            curr = nxt
    merged.append(curr)

    logger.info("[NODE-2][STEP 3] Silero VAD generated %d speech segments.", len(merged))
    return merged


def slice_44k_audio(input_44k_path: str, start_sec: float, end_sec: float, output_chunk_path: str) -> None:
    """
    Step 4: Dual-Fidelity Slicing.
    Slices the ORIGINAL high-resolution 44.1kHz stereo vocals using exact timestamps.
    """
    ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
    dur = round(end_sec - start_sec, 3)
    cmd = [
        ffmpeg_bin,
        "-y",
        "-ss", str(start_sec),
        "-t", str(dur),
        "-i", input_44k_path,
        "-acodec", "pcm_s16le",
        "-ar", "44100",
        "-ac", "2",
        output_chunk_path,
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"Slicing 44k audio failed: {proc.stderr.decode('utf-8', errors='ignore')}")


async def process_node2_separation(
    job_id: str,
    workspace_id: str,
    source_r2_key: str,
    client: Any = None,
) -> Dict[str, Any]:
    """
    Executes Node 2 end-to-end:
    1. Headless FFmpeg 44.1kHz audio extraction from R2 streaming URL.
    2. Demucs htdemucs isolation (vocals.wav + no_vocals.wav).
    3. Resample vocals to 16kHz mono for Silero VAD.
    4. Slice original 44.1kHz stereo vocals into high-fidelity chunks.
    5. Upload stems & chunks to R2.
    6. Batch insert chunks into Convex dubbingChunks with status PENDING_ASR.
    7. Ephemeral cleanup of worker disk.
    """
    user_client = client or convex_db._get_service_role_client()
    tmp_dir = Path(tempfile.mkdtemp(prefix=f"node2_{job_id[:8]}_"))
    logger.info("================================================================")
    logger.info("[NODE-2] STARTING SEPARATION & SEGMENTATION FOR JOB %s", job_id)
    logger.info("================================================================")

    try:
        # Step 1: Headless extraction
        source_audio_44k = str(tmp_dir / "source_44k_stereo.wav")
        logger.info("[NODE-2] Generating presigned streaming URL for R2 key: %s", source_r2_key)
        presigned_get_url = r2.signed_url(source_r2_key, ttl_seconds=3600, inline=True)
        await asyncio.to_thread(extract_44k_audio_from_url, presigned_get_url, source_audio_44k)

        # Step 2: Demucs Isolation
        demucs_out_dir = str(tmp_dir / "demucs_out")
        vocals_path, no_vocals_path = await asyncio.to_thread(run_demucs_isolation, source_audio_44k, demucs_out_dir)

        # Upload no_vocals.wav (background track stem) and vocals.wav to R2
        bg_r2_key = f"dubbing/{workspace_id}/{job_id}/stems/no_vocals.wav"
        vocals_r2_key = f"dubbing/{workspace_id}/{job_id}/stems/vocals.wav"
        logger.info("[NODE-2] Uploading separated stems to R2...")
        await asyncio.to_thread(r2.upload_file, bg_r2_key, no_vocals_path, mime="audio/wav")
        await asyncio.to_thread(r2.upload_file, vocals_r2_key, vocals_path, mime="audio/wav")

        # Step 3: Silero VAD 16k mono resampling
        vocals_16k_mono = str(tmp_dir / "vocals_16k_mono.wav")
        await asyncio.to_thread(resample_to_16k_mono, vocals_path, vocals_16k_mono)
        segments = await asyncio.to_thread(get_speech_segments_silero, vocals_16k_mono)

        # Step 4 & 5: Slice original 44.1k vocals and upload to R2
        chunks_for_convex: List[Dict[str, Any]] = []
        chunks_dir = tmp_dir / "chunks"
        chunks_dir.mkdir(exist_ok=True)

        for idx, seg in enumerate(segments):
            chunk_filename = f"chunk_{idx:03d}.wav"
            local_chunk_path = str(chunks_dir / chunk_filename)
            await asyncio.to_thread(slice_44k_audio, vocals_path, seg["start"], seg["end"], local_chunk_path)

            chunk_r2_key = f"dubbing/{workspace_id}/{job_id}/chunks/vocal_chunk_{idx:03d}.wav"
            await asyncio.to_thread(r2.upload_file, chunk_r2_key, local_chunk_path, mime="audio/wav")

            duration = round(seg["end"] - seg["start"], 3)
            chunks_for_convex.append({
                "legacyId": str(uuid.uuid4()),
                "chunkIndex": idx,
                "startTime": seg["start"],
                "endTime": seg["end"],
                "speechDuration": duration,
                "vad_duration_sec": duration,
                "kurdish_raw_audio_url": chunk_r2_key,
                "ttsAudioR2Key": "",
                "status": "PENDING_ASR",
            })

        # Step 6: Batch insert into Convex
        logger.info("[NODE-2] Registering %d chunks in Convex state machine...", len(chunks_for_convex))
        c = convex_db._get_client()
        await asyncio_to_thread_batch_insert(
            c,
            job_id=job_id,
            bg_audio_r2_key=bg_r2_key,
            isolated_vocals_r2_key=vocals_r2_key,
            chunks=chunks_for_convex,
        )

        logger.info("[NODE-2] SUCCESS: Node 2 (Separation & Segmentation) complete for job %s!", job_id)
        return {
            "success": True,
            "chunks_count": len(chunks_for_convex),
            "bg_audio_r2_key": bg_r2_key,
            "isolated_vocals_r2_key": vocals_r2_key,
            "chunks": chunks_for_convex,
        }

    except Exception as e:
        logger.exception("[NODE-2] CRITICAL ERROR during Node 2 execution for job %s: %s", job_id, e)
        # Update Convex job status to failed with exact diagnostic error
        try:
            c = convex_db._get_client()
            err_details = f"Node 2 Separation Failed: {str(e)}"
            await asyncio.to_thread(
                c.mutation,
                "dubbingJobs:updateStatusInternal",
                {
                    "__internalApiKey": os.getenv("INTERNAL_API_KEY", ""),
                    "jobId": job_id,
                    "status": "failed",
                    "error": err_details,
                }
            )
        except Exception as patch_err:
            logger.error("[NODE-2] Could not patch failure status to Convex: %s", patch_err)
        raise

    finally:
        # Step 7: Ephemeral Disk Cleanup & GPU Flush
        logger.info("[NODE-2] Wiping ephemeral scratch directory %s...", tmp_dir)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        gc.collect()


async def asyncio_to_thread_batch_insert(c: Any, job_id: str, bg_audio_r2_key: str, isolated_vocals_r2_key: str, chunks: List[Dict[str, Any]]):
    def _do():
        return c.mutation(
            "dubbingChunks:batchInsertChunksInternal",
            {
                "__internalApiKey": os.getenv("INTERNAL_API_KEY", ""),
                "jobId": job_id,
                "bgAudioR2Key": bg_audio_r2_key,
                "isolatedVocalsR2Key": isolated_vocals_r2_key,
                "chunks": chunks,
            },
        )
    return await asyncio.to_thread(_do)
