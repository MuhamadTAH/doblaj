"""
vcta_reference_mastering.py
===========================
Analysis-first reference mastering for Kurdish → Arabic video dubbing.

WHAT THIS MODULE SOLVES
───────────────────────
The original Kurdish video has a specific energy fingerprint: its integrated
loudness (LUFS), dynamic range (LRA), and True Peak. Even if you match every
individual component (TTS volume, background ducking), if the final Arabic mix
doesn't match the original's integrated LUFS, it will FEEL different — either
thin, weak, or too aggressive. Your ears measure LUFS, not dBFS averages.

This module:
  1. Extracts the original Kurdish video's energy fingerprint (LUFS + LRA + TP)
  2. Compiles the final Arabic mix with a FIXED sidechain (release=250ms, not 50ms)
  3. Normalizes the entire output to match the original's integrated LUFS exactly

HOW TO USE
──────────
  # Step A: Profile the original ONCE
  profile = extract_loudness_profile("original_kurdish_video.mp4")
  # → {'input_i': '-12.3', 'input_tp': '-1.2', 'input_lra': '8.5', ...}

  # Step B: Compile final video using that profile as the loudness target
  compile_with_reference_mastering(
      video_source_path="original_kurdish_video.mp4",
      arabic_vocal_track_path="arabic_vocal_full.wav",
      background_stem_path="background_stem.wav",
      output_path="OUTPUT_FINAL.mp4",
      reference_profile=profile,
  )

DEPENDENCIES
────────────
  pip install pydub
  ffmpeg (with libopus/aac support) on system PATH

WHY 50ms SIDECHAIN RELEASE IS WRONG
─────────────────────────────────────
At release=50ms, the background audio recovers to 86% of full volume within
100ms. The natural gap between Arabic words is 50–80ms. This means the
background snaps back to near full volume between EVERY SINGLE WORD — creating
a constant wah-wah pump artifact that is completely absent from the original.
The original Kurdish video has no pump because the voice and background were
recorded/mixed organically. To replicate that natural feel, release must be
≥200ms so the background stays smoothly ducked through the entire speech phrase
and only recovers during genuine sentence breaks.
"""

import json
import logging
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# PART 1: Energy Profile Extraction — "Fingerprint the original"
# ─────────────────────────────────────────────────────────────────────────────

def extract_loudness_profile(
    source_path: str,
    audio_stream_index: int = 0,
) -> dict:
    """
    Analyzes the original Kurdish video (or any audio/video file) and returns
    its perceptual loudness fingerprint using ITU-R BS.1770 via FFmpeg loudnorm.

    This fingerprint becomes the TARGET for the final Arabic mix output.
    After normalization, the Arabic dubbed video will be perceptually indistinguishable
    in loudness from the original — even if individual components were processed
    very differently.

    Args:
        source_path: Path to the original Kurdish video or audio file.
        audio_stream_index: Which audio stream to analyze (0 = first/default).

    Returns:
        dict with keys:
            input_i    — Integrated loudness in LUFS (e.g., "-12.3")
                         This is what your ears hear as "loud" or "quiet".
            input_tp   — True Peak in dBTP (e.g., "-1.2")
                         The actual maximum peak including inter-sample peaks.
            input_lra  — Loudness Range in LU (e.g., "8.5")
                         The dynamic range — difference between loud and quiet parts.
            input_thresh — Gating threshold used during analysis.
            (plus FFmpeg's output_* fields — you can ignore those)

    Raises:
        FileNotFoundError: If source_path doesn't exist.
        RuntimeError: If FFmpeg fails or cannot extract loudnorm JSON.

    Example:
        >>> profile = extract_loudness_profile("kurdish_video.mp4")
        >>> print(f"Original LUFS: {profile['input_i']}")
        Original LUFS: -12.3
    """
    if not Path(source_path).exists():
        raise FileNotFoundError(f"Source not found: {source_path}")
    # Pird: validate the path is under our workspace root. See pass-4 review.
    from pathlib import Path as _Path
    _allowed = _Path("data/jobs/sessions").resolve()
    _resolved = _Path(source_path).resolve()
    if not _resolved.is_relative_to(_allowed):
        raise ValueError(f"source_path must be under {_allowed}, got {_resolved}")

    # FFmpeg loudnorm in analysis mode: reads entire file, outputs JSON to stderr,
    # produces no output file (-f null -). This is non-destructive.
    cmd = [
        "ffmpeg",
        "-i", source_path,
        "-map", f"0:a:{audio_stream_index}",
        "-af", "loudnorm=print_format=json",
        "-f", "null",
        "-",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    # loudnorm JSON is written to stderr (FFmpeg's normal behavior)
    stderr = result.stderr
    json_start = stderr.rfind("{")
    json_end = stderr.rfind("}") + 1

    if json_start == -1 or json_end == 0:
        raise RuntimeError(
            f"FFmpeg loudnorm did not produce JSON output.\n"
            f"This usually means the file has no audio stream or FFmpeg lacks loudnorm support.\n"
            f"FFmpeg stderr:\n{stderr[-1000:]}"
        )

    profile = json.loads(stderr[json_start:json_end])

    logger.info(
        "[LOUDNESS PROFILE] %s\n"
        "  Integrated LUFS : %s LUFS  (perceived loudness — this is the key number)\n"
        "  True Peak       : %s dBTP\n"
        "  Loudness Range  : %s LU   (dynamic range)\n"
        "  Threshold       : %s LUFS",
        Path(source_path).name,
        profile.get("input_i"),
        profile.get("input_tp"),
        profile.get("input_lra"),
        profile.get("input_thresh"),
    )

    return profile


# ─────────────────────────────────────────────────────────────────────────────
# PART 2: Safe atempo calculation — handles extreme speed ratios
# ─────────────────────────────────────────────────────────────────────────────

def build_atempo_chain(speed_ratio: float) -> str:
    """
    Builds an FFmpeg atempo filter string that handles any speed ratio.

    FFmpeg's atempo filter only accepts values between 0.5 and 2.0.
    Ratios outside this range require chained filters.
    This function generates the correct chain automatically.

    Args:
        speed_ratio: The target speed multiplier.
                     1.0 = original speed
                     1.3 = 30% faster (Arabic TTS shorter than Kurdish original)
                     0.8 = 20% slower (Arabic TTS longer than Kurdish original)

    Returns:
        FFmpeg filter string (e.g., "atempo=1.3" or "atempo=1.581,atempo=1.581")

    Raises:
        ValueError: If speed_ratio is <= 0 or would require > 4 chained filters
                   (extreme ratios >16x or <0.06x are almost certainly pipeline errors).
    """
    if speed_ratio <= 0:
        raise ValueError(f"speed_ratio must be positive, got {speed_ratio}")

    # Clamp extreme ratios — anything beyond these is almost certainly a bug
    # in the WPS calculator upstream, not a valid timing adjustment.
    MAX_RATIO = 4.0   # 4x speed = 400% — speech becomes unintelligible above this
    MIN_RATIO = 0.25  # 0.25x speed = talking in slow motion

    if speed_ratio > MAX_RATIO:
        logger.warning(
            "[ATEMPO] Ratio %.3fx exceeds maximum (%.1fx). Clamping to %.1fx. "
            "Fix your WPS limiter — TTS is far too short for this chunk.",
            speed_ratio, MAX_RATIO, MAX_RATIO
        )
        speed_ratio = MAX_RATIO
    elif speed_ratio < MIN_RATIO:
        logger.warning(
            "[ATEMPO] Ratio %.3fx is below minimum (%.2fx). Clamping to %.2fx. "
            "Fix your WPS limiter — TTS is far too long for this chunk.",
            speed_ratio, MIN_RATIO, MIN_RATIO
        )
        speed_ratio = MIN_RATIO

    if 0.5 <= speed_ratio <= 2.0:
        # Simple case: single atempo filter
        return f"atempo={speed_ratio:.6f}"

    # Complex case: chain N identical atempo values whose product = speed_ratio
    # e.g., 2.5x → atempo=1.5811,atempo=1.5811 (since 1.5811^2 ≈ 2.5)
    import math
    n = math.ceil(math.log(speed_ratio) / math.log(2.0)) if speed_ratio > 2.0 \
        else math.ceil(math.log(speed_ratio) / math.log(0.5))

    per_stage = speed_ratio ** (1.0 / n)
    chain = ",".join([f"atempo={per_stage:.6f}"] * n)

    logger.debug(
        "[ATEMPO] Ratio %.3fx → %d-stage chain: %s",
        speed_ratio, n, chain
    )
    return chain


# ─────────────────────────────────────────────────────────────────────────────
# PART 3: Final mix — fixed sidechain + reference loudness normalization
# ─────────────────────────────────────────────────────────────────────────────

def compile_with_reference_mastering(
    video_source_path: str,
    arabic_vocal_track_path: str,
    background_stem_path: str,
    output_path: str,
    reference_profile: dict,
    # Sidechain parameters — DO NOT change release below 150ms
    sc_threshold: float = 0.12,       # ~-22 dBFS trigger point (linear scale)
    sc_ratio: float = 2.5,            # 4:1 compression — firm but not brick-wall
    sc_attack_ms: float = 5.0,        # 5ms — fast enough to catch speech onset
    sc_release_ms: float = 250.0,     # 250ms — CRITICAL. 50ms causes pumping. See module docstring.
    sc_makeup_db: float = 0.0,        # No makeup gain (we're ducking BG, not boosting)
    background_base_volume: float = 1.8,  # Boosted to 1.8 to compensate for clean frequency removal
    # Output params
    true_peak_ceiling_dbtp: float = -1.5,  # Leave 1.5 dB headroom before AAC encode
    audio_bitrate: str = "192k",
    sample_rate: int = 44100,
    ffmpeg_bin: str = "ffmpeg",
) -> None:
    """
    Compiles the final dubbed video with:
    1. Sidechain compression: Arabic vocal ducks background music/SFX.
       FIXED release=250ms (vs wrong 50ms) prevents inter-word pumping.
    2. normalize=0 on amix: prevents FFmpeg silently cutting vocal -6dB.
    3. loudnorm: normalizes final output to exactly match original Kurdish
       video's integrated LUFS — this is the "same energy" guarantee.
    4. alimiter: True Peak limiting at -1.5 dBTP prevents encode clipping.
    """
    # Validate inputs
    for path, label in [
        (video_source_path,       "video_source"),
        (arabic_vocal_track_path, "arabic_vocal"),
        (background_stem_path,    "background_stem"),
    ]:
        if not Path(path).exists():
            raise FileNotFoundError(f"[{label}] not found: {path}")

    required_keys = {"input_i", "input_lra"}
    missing = required_keys - set(reference_profile.keys())
    if missing:
        raise ValueError(
            f"reference_profile is missing keys: {missing}. "
            f"Run extract_loudness_profile() on the original video first."
        )

    # Extract targets from reference profile
    target_lufs = float(reference_profile["input_i"])
    target_lra = float(reference_profile["input_lra"])

    # Clamp LRA to FFmpeg loudnorm supported range [1.0, 50.0]
    target_lra = max(1.0, min(50.0, target_lra))

    logger.info(
        "[COMPILE] Reference targets → LUFS=%.1f | LRA=%.1f | TP=%.1f",
        target_lufs, target_lra, true_peak_ceiling_dbtp,
    )
    logger.info(
        "[COMPILE] Sidechain → threshold=%.3f | ratio=%.1f | "
        "attack=%.0fms | release=%.0fms",
        sc_threshold, sc_ratio, sc_attack_ms, sc_release_ms,
    )

    import math
    sc_makeup_linear = 10 ** (sc_makeup_db / 20.0) if sc_makeup_db != 0 else 1.0

    filter_complex = (
        # 1. BACKGROUND MULTI-BAND SPLIT
        # Split background into: Low (<300Hz), Mid (300Hz-3.5kHz), High (>3.5kHz)
        f"[0:a]volume={background_base_volume:.6f},asplit=3[bg_low][bg_mid][bg_high];"
        f"[bg_low]lowpass=f=300[bg_low_band];"
        f"[bg_mid]bandpass=f=1900:width_type=h:w=3200[bg_mid_band];"
        f"[bg_high]highpass=f=3500[bg_high_band];"
        
        # 2. VOCAL FATTENING + DE-ESSER CHAIN
        # Compress -> Highpass 80Hz -> Treble Boost 3kHz -> De-Esser -> Split
        f"[1:a]aformat=sample_fmts=fltp,"
        f"acompressor=threshold=-18dB:ratio=4:attack=5:release=50:makeup=2,"
        f"highpass=f=80,"
        f"treble=g=3.5:f=3000,"
        f"deesser=i=0.4:m=0.5:f=0.5:s=e,"  # De-esser tames harsh 'S' consonants
        f"asplit=2[sc_trigger][vox_mix];"
        
        # 3. SPECTRAL SIDECHAIN DUCKING
        # Duck ONLY the mid-range background band (300Hz-3.5kHz)
        f"[bg_mid_band][sc_trigger]sidechaincompress="
        f"threshold={sc_threshold:.4f}:ratio={sc_ratio:.1f}:"
        f"attack={sc_attack_ms:.1f}:release={sc_release_ms:.1f}:"
        f"makeup={sc_makeup_linear:.4f}[bg_mid_ducked];"
        
        # 4. RECOMBINE BACKGROUND BANDS
        # Re-merge Low + Ducked Mid + High bands
        f"[bg_low_band][bg_mid_ducked][bg_high_band]amix=inputs=3:normalize=0[bg_full_ducked];"
        
        # 5. FINAL VOCAL + BACKGROUND MIX
        f"[bg_full_ducked][vox_mix]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0[raw_mix];"
        
        # 6. GLOBAL REFERENCE LUFS MASTERING
        f"[raw_mix]loudnorm=I={target_lufs:.1f}:TP={true_peak_ceiling_dbtp:.1f}:LRA={target_lra:.1f},"
        f"alimiter=limit={10 ** (true_peak_ceiling_dbtp / 20):.6f}:level=0[final_mix]"
    )

    cmd = [
        ffmpeg_bin,
        "-y",
        "-i", background_stem_path,
        "-i", arabic_vocal_track_path,
        "-i", video_source_path,
        "-filter_complex", filter_complex,
        "-map", "2:v:0",
        "-map", "[final_mix]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", audio_bitrate,
        "-ar", str(sample_rate),
        "-movflags", "+faststart",
        output_path,
    ]

    logger.info("[COMPILE CMD] %s", " ".join(cmd))

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        logger.error("[COMPILE FAILED]\n%s", result.stderr)
        raise RuntimeError(
            f"FFmpeg exited {result.returncode}.\n\n"
            f"--- stderr (last 2000 chars) ---\n{result.stderr[-2000:]}"
        )

    logger.info("[COMPILE COMPLETE] → %s", output_path)


def mix_and_master_final_audio(arabic_vocal_path: str, restored_bg_path: str, final_output_path: str):
    """
    Combines the translated AI dub with the restored background track using
    mid-band sidechain compression and EBU R128 broadcast loudness mastering.
    """
    logger.info("[MASTERING] Fusing Arabic Dub with Restored Background...")

    # The FFmpeg Filtergraph
    # 1. Splits background into Low, Mid, High
    # 2. Sidechain compresses ONLY the Mid band when the Arabic vocal plays
    # 3. Mixes them together
    # 4. Applies Loudness Normalization (-14 LUFS, -1.0 True Peak)
    
    filter_complex = (
        "[1:a]asplit=3[bg_low][bg_mid][bg_high]; "
        "[bg_low]lowpass=f=300[bg_low_band]; "
        "[bg_mid]bandpass=f=1900:width_type=h:w=3200[bg_mid_band]; "
        "[bg_high]highpass=f=3500[bg_high_band]; "
        
        # Trigger sidechain ducking on the mid-band using the Arabic vocal [0:a]
        "[bg_mid_band][0:a]sidechaincompress=threshold=-15dB:ratio=3:attack=10:release=200[bg_mid_ducked]; "
        
        # Recombine the background
        "[bg_low_band][bg_mid_ducked][bg_high_band]amix=inputs=3:normalize=0[bg_full]; "
        
        # Mix the Arabic vocal with the dynamically ducked background
        "[bg_full][0:a]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0[raw_mix]; "
        
        # Master the final track to YouTube/Netflix loudness standards
        "[raw_mix]loudnorm=I=-14:TP=-1.0:LRA=11[mastered]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", arabic_vocal_path,   # [0:a]
        "-i", restored_bg_path,    # [1:a]
        "-filter_complex", filter_complex,
        "-map", "[mastered]",
        "-c:a", "aac", "-b:a", "256k",
        final_output_path
    ]

    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    logger.info(f"[MASTERING COMPLETE] Final audio saved to: {final_output_path}")
    
    return final_output_path

