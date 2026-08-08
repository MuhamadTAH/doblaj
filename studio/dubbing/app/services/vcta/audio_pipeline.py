import subprocess
import logging
from pathlib import Path
from typing import Optional
from pydub import AudioSegment
from pydub.silence import detect_leading_silence

logger = logging.getLogger(__name__)

# Pird: every FFmpeg/file output is constrained under this root.
# Mirrors the same constant in isolation.py. See pass-4 review.
ALLOWED_OUTPUT_ROOT = Path("data/jobs/sessions").resolve()


def _safe_resolve(path: str, label: str) -> Path:
    """Resolve a caller-supplied path and verify it's under ALLOWED_OUTPUT_ROOT.
    Raises ValueError otherwise. Prevents accidental writes outside the workspace."""
    resolved = Path(path).resolve()
    if not resolved.is_relative_to(ALLOWED_OUTPUT_ROOT):
        raise ValueError(
            f"{label} must be under {ALLOWED_OUTPUT_ROOT}, got {resolved}"
        )
    return resolved

# ─────────────────────────────────────────────────────────────────────────────
# TUNEABLE CONSTANTS — adjust per project, don't hardcode in call sites
# ─────────────────────────────────────────────────────────────────────────────

# The max average dBFS a "mostly speech" original chunk should have.
# If original avg exceeds this, the chunk is noise-dominated and we fall back
# to FALLBACK_VOCAL_TARGET_DBFS instead of matching its loudness blindly.
NOISE_DOMINATED_THRESHOLD_DBFS: float = -15.0

# Fixed target loudness when we cannot use the original as a clean reference.
# -20 dBFS avg is a safe, clear vocal presence target for speech content.
FALLBACK_VOCAL_TARGET_DBFS: float = -20.0

# Anything louder than this on the output risks digital clipping after final AAC encode.
# -1.0 dBFS gives a 1dB true peak headroom margin.
OUTPUT_CEILING_DBFS: float = -1.0

# If final chunk duration exceeds original by more than this, emit a WARNING.
# This catches TTS overruns that will cause inter-chunk timeline drift.
DURATION_DRIFT_WARN_THRESHOLD_MS: int = 50


# ─────────────────────────────────────────────────────────────────────────────
# STEPS 1–3: Chunk-level mastering and alignment
# ─────────────────────────────────────────────────────────────────────────────

def master_and_align_chunk(
    original_chunk_path: str,
    tts_chunk_path: str,
    output_path: str,
    # Step 1 params
    leading_silence_threshold_dbfs: float = -40.0,
    silence_detection_chunk_ms: int = 1,          # 1ms resolution — don't use 10ms default
    # Step 2 params
    vocal_stem_path: Optional[str] = None,         # Pass this if you have isolated Kurdish vocal
    presence_boost_db: float = 1.5,
    output_ceiling_dbfs: float = OUTPUT_CEILING_DBFS,
    noise_dominated_threshold: float = NOISE_DOMINATED_THRESHOLD_DBFS,
    fallback_vocal_target: float = FALLBACK_VOCAL_TARGET_DBFS,
    # Step 3 / export params
    export_format: str = "wav",                    # WAV for intermediate — final encode is in FFmpeg
) -> dict:
    """
    Full chunk pipeline: analyze → master → align → export.
    """

    for path, label in [(original_chunk_path, "original"), (tts_chunk_path, "tts")]:
        if not Path(path).exists():
            raise FileNotFoundError(f"[{label}] not found: {path}")
        # Pird: validate the input path is under our workspace root.
        # See pass-4 review.
        _safe_resolve(path, label)

    # ── STEP 1: Source Analysis ───────────────────────────────────────────────
    original: AudioSegment = AudioSegment.from_file(original_chunk_path)
    
    # Use vocal stem for precise silence detection if available, to avoid background noise triggering it
    silence_target = original
    if vocal_stem_path and Path(vocal_stem_path).exists():
        silence_target = AudioSegment.from_file(vocal_stem_path)

    original_duration_ms: int = len(original)
    original_avg_dbfs: float = original.dBFS
    original_peak_dbfs: float = original.max_dBFS

    leading_silence_ms: int = detect_leading_silence(
        silence_target,
        silence_threshold=leading_silence_threshold_dbfs,
        chunk_size=silence_detection_chunk_ms,
    )
    active_speaking_duration_ms: int = original_duration_ms - leading_silence_ms

    logger.info(
        "[STEP-1 ANALYSIS] chunk=%s | dur=%dms | avg_dBFS=%.2f | "
        "peak_dBFS=%.2f | leading_silence=%dms | active_speech=%dms",
        Path(original_chunk_path).name,
        original_duration_ms,
        original_avg_dbfs,
        original_peak_dbfs,
        leading_silence_ms,
        active_speaking_duration_ms,
    )

    # ── STEP 2: Gain Staging & Auto-Mastering ────────────────────────────────
    tts_audio: AudioSegment = AudioSegment.from_file(tts_chunk_path)

    if tts_audio.dBFS == float("-inf"):
        raise ValueError(
            f"TTS audio is completely silent — likely a Fish Audio generation failure.\n"
            f"File: {tts_chunk_path}"
        )

    tts_avg_dbfs: float = tts_audio.dBFS

    reference_source: str
    target_dbfs: float

    if vocal_stem_path and Path(vocal_stem_path).exists():
        reference_audio = AudioSegment.from_file(vocal_stem_path)
        target_dbfs = reference_audio.dBFS
        reference_source = "vocal_stem"
    elif original_avg_dbfs < noise_dominated_threshold:
        target_dbfs = original_avg_dbfs
        reference_source = "original_full_mix"
    else:
        target_dbfs = fallback_vocal_target
        reference_source = "fallback_target"
        logger.warning(
            "[STEP-2 NOISE WARNING] Original avg dBFS (%.2f) exceeds noise threshold (%.2f). "
            "Chunk appears noise-dominated. Using fallback vocal target (%.2f dBFS) "
            "instead of matching original. Pass vocal_stem_path for accurate gain staging.",
            original_avg_dbfs,
            noise_dominated_threshold,
            fallback_vocal_target,
        )

    gain_delta_db: float = target_dbfs - tts_avg_dbfs
    total_gain_db: float = gain_delta_db + presence_boost_db

    mastered_tts: AudioSegment = tts_audio + total_gain_db

    safety_triggered: bool = False
    safety_pullback_db: float = 0.0

    if mastered_tts.max_dBFS > output_ceiling_dbfs:
        safety_pullback_db = mastered_tts.max_dBFS - output_ceiling_dbfs
        mastered_tts = mastered_tts - safety_pullback_db
        safety_triggered = True
        logger.warning(
            "[STEP-2 SAFETY CLIP] Peak exceeded ceiling by %.2f dB. "
            "Pulled back %.2f dB. Final peak: %.2f dBFS. "
            "If this fires frequently, reduce presence_boost_db or tighten WPS limits.",
            safety_pullback_db,
            safety_pullback_db,
            mastered_tts.max_dBFS,
        )

    logger.info(
        "[STEP-2 MASTERING] ref=%s | target=%.2f | tts_avg=%.2f | "
        "gain_applied=%.2f dB | final_peak=%.2f | safety=%s",
        reference_source,
        target_dbfs,
        tts_avg_dbfs,
        total_gain_db,
        mastered_tts.max_dBFS,
        safety_triggered,
    )

    # ── STEP 3: Timeline Restoration ─────────────────────────────────────────
    silence_prefix: AudioSegment = AudioSegment.silent(
        duration=leading_silence_ms,
        frame_rate=mastered_tts.frame_rate,
    )

    final_chunk: AudioSegment = silence_prefix + mastered_tts
    final_duration_ms: int = len(final_chunk)
    duration_delta_ms: int = final_duration_ms - original_duration_ms

    if duration_delta_ms > DURATION_DRIFT_WARN_THRESHOLD_MS:
        logger.warning(
            "[STEP-3 DURATION OVERFLOW] final=%dms | original=%dms | overflow=+%dms. "
            "Arabic TTS exceeds available slot. This causes inter-chunk timeline drift. "
            "Action required: tighten Word-Per-Second limit for this chunk upstream.",
            final_duration_ms,
            original_duration_ms,
            duration_delta_ms,
        )
    elif duration_delta_ms < -DURATION_DRIFT_WARN_THRESHOLD_MS:
        logger.debug(
            "[STEP-3 DURATION UNDERRUN] final=%dms | original=%dms | gap=%dms. "
            "Trailing gap exists — acceptable, next chunk is unaffected.",
            final_duration_ms,
            original_duration_ms,
            abs(duration_delta_ms),
        )

    if export_format == "mp3":
        final_chunk.export(output_path, format="mp3", bitrate="192k")
    else:
        final_chunk.export(output_path, format="wav")

    logger.info(
        "[STEP-3 ALIGNED] leading_silence=%dms | active_content=%dms | "
        "final=%dms | original=%dms | delta=%+dms | exported=%s",
        leading_silence_ms,
        len(mastered_tts),
        final_duration_ms,
        original_duration_ms,
        duration_delta_ms,
        output_path,
    )

    return {
        "original_duration_ms": original_duration_ms,
        "original_avg_dbfs": round(original_avg_dbfs, 2),
        "original_peak_dbfs": round(original_peak_dbfs, 2),
        "leading_silence_ms": leading_silence_ms,
        "active_speaking_duration_ms": active_speaking_duration_ms,
        "gain_reference_source": reference_source,
        "gain_target_dbfs": round(target_dbfs, 2),
        "tts_input_avg_dbfs": round(tts_avg_dbfs, 2),
        "total_gain_applied_db": round(total_gain_db, 2),
        "mastered_peak_dbfs": round(mastered_tts.max_dBFS, 2),
        "safety_clip_triggered": safety_triggered,
        "safety_pullback_db": round(safety_pullback_db, 2),
        "final_duration_ms": final_duration_ms,
        "duration_delta_ms": duration_delta_ms,
        "output_path": output_path,
    }

def compile_final_video(
    video_source_path: str,
    arabic_vocal_track_path: str,
    background_stem_path: str,
    output_path: str,
    background_duck_db: float = -8.0,
    audio_bitrate: str = "192k",
    sample_rate: int = 44100,
    ffmpeg_bin: str = "ffmpeg",
) -> None:
    for path, label in [
        (video_source_path, "video_source"),
        (arabic_vocal_track_path, "arabic_vocal"),
        (background_stem_path, "background_stem"),
    ]:
        if not Path(path).exists():
            raise FileNotFoundError(f"[{label}] not found: {path}")
        # Pird: validate the path is under our workspace root.
        _safe_resolve(path, label)

    bg_volume_linear: float = 10 ** (background_duck_db / 20)

    logger.info(
        "[STEP-4 MIX] Applying dynamic sidechain compression (ducking) for background track..."
    )

    filter_complex: str = (
        f"[0:a]volume={bg_volume_linear:.6f}[bg_scaled];"
        f"[1:a]asplit=2[sc][mix];"
        f"[bg_scaled][sc]sidechaincompress=threshold=0.04:ratio=6:attack=5:release=50[bg_ducked];"
        f"[bg_ducked][mix]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0[mixed];"
        f"[mixed]alimiter=limit=-0.5dB[final_mix]"
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
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", audio_bitrate,
        "-ar", str(sample_rate),
        "-movflags", "+faststart",
        output_path,
    ]

    logger.info("[STEP-4 FFMPEG CMD] %s", " ".join(cmd))

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        logger.error("[STEP-4 FFMPEG FAILED]\n%s", result.stderr)
        raise RuntimeError(
            f"FFmpeg exited with code {result.returncode}.\n\n"
            f"--- stderr ---\n{result.stderr}"
        )

    logger.info("[STEP-4 COMPLETE] → %s", output_path)
