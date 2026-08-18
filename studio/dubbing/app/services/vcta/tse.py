import os
import logging
import numpy as np
import soundfile as sf
import torch
import librosa

logger = logging.getLogger(__name__)

_CLASSIFIER_CACHE = None

def get_tse_classifier():
    """
    Loads and caches SpeechBrain ECAPA-VoxCeleb model for Target Speaker Extraction.
    """
    global _CLASSIFIER_CACHE
    if _CLASSIFIER_CACHE is None:
        try:
            from speechbrain.inference.speaker import EncoderClassifier
            device = "cuda" if torch.cuda.is_available() else "cpu"
            logger.info(f"[TSE] Initializing SpeechBrain ECAPA-VoxCeleb model on {device}...")
            _CLASSIFIER_CACHE = EncoderClassifier.from_hparams(
                source="speechbrain/spkrec-ecapa-voxceleb",
                run_opts={"device": device}
            )
            logger.info("[TSE] SpeechBrain model loaded successfully.")
        except Exception as e:
            logger.warning(f"[TSE] Failed to load SpeechBrain model: {e}")
            _CLASSIFIER_CACHE = None
    return _CLASSIFIER_CACHE


def extract_enrollment_reference(
    audio_path: str,
    output_ref_path: str,
    target_duration_sec: float = 8.0,
    min_anchor_sec: float = 3.0
) -> str:
    """
    Step 1 (VAD-Anchored Dynamic Enrollment):
    Scans audio using Silero VAD to find the FIRST continuous block of real human speech
    lasting at least `min_anchor_sec` (e.g., 3.0s). Extracts host_enrollment_ref.wav dynamically
    from that anchor point, completely bypassing intro music/montages/explosions.
    """
    logger.info(f"[TSE Step 1] Hunting for biological human speech anchor in {audio_path} via Silero VAD...")
    audio, sr = sf.read(audio_path, dtype='float32')

    # Convert to mono 16kHz for Silero VAD
    if audio.ndim > 1:
        mono_audio = audio.mean(axis=1)
    else:
        mono_audio = audio

    if sr != 16000:
        mono_16k = librosa.resample(mono_audio, orig_sr=sr, target_sr=16000)
    else:
        mono_16k = mono_audio

    anchor_start_sec = 0.0
    anchor_end_sec = target_duration_sec

    try:
        from silero_vad import load_silero_vad, get_speech_timestamps
        vad_model = load_silero_vad()
        wav_tensor = torch.from_numpy(mono_16k)
        
        # Detect active human speech blocks
        timestamps = get_speech_timestamps(
            wav_tensor,
            vad_model,
            sampling_rate=16000,
            min_speech_duration_ms=int(min_anchor_sec * 1000)
        )
        
        if timestamps:
            # Grab the FIRST continuous block of human speech >= min_anchor_sec
            first_block = timestamps[0]
            anchor_start_sec = first_block['start'] / 16000.0
            anchor_end_sec = min(anchor_start_sec + target_duration_sec, first_block['end'] / 16000.0)
            
            # Ensure clip length is at least min_anchor_sec if possible
            if (anchor_end_sec - anchor_start_sec) < min_anchor_sec:
                anchor_end_sec = min(anchor_start_sec + target_duration_sec, len(mono_16k) / 16000.0)

            logger.info(
                f"[TSE Step 1] Biological human speech anchor found! "
                f"Extracting enrollment clip from {anchor_start_sec:.2f}s to {anchor_end_sec:.2f}s."
            )
        else:
            logger.warning(
                f"[TSE Step 1] No continuous speech block >={min_anchor_sec}s found by Silero VAD. "
                f"Falling back to default 0:00 - {target_duration_sec}s clip."
            )
    except Exception as vad_err:
        logger.warning(f"[TSE Step 1] Silero VAD anchor extraction warning: {vad_err}. Falling back to default.")

    start_sample = int(anchor_start_sec * sr)
    end_sample = int(anchor_end_sec * sr)

    if end_sample <= start_sample:
        end_sample = min(len(audio), start_sample + int(target_duration_sec * sr))

    ref_audio = audio[start_sample:end_sample]
    sf.write(output_ref_path, ref_audio, sr, subtype='FLOAT')
    logger.info(f"[TSE Step 1] Dynamic enrollment reference saved to: {output_ref_path}")
    return output_ref_path


def compute_zerobleed_tse_mask(
    similarities: np.ndarray, 
    base_threshold: float = 0.55, 
    median_window_frames: int = 21,
    fps: int = 50,
    crossfade_ms: int = 50
) -> np.ndarray:
    """
    Generates a strict 1.0 / 0.0 mask with a mathematically perfect crossfade.
    Prevents fractional host audio from leaking into the background stem.
    """
    if len(similarities) == 0:
        return np.array([], dtype=np.float32)

    from scipy.signal import medfilt

    kernel_size = median_window_frames
    if kernel_size % 2 == 0:
        kernel_size += 1
    if kernel_size > len(similarities):
        kernel_size = len(similarities) if len(similarities) % 2 != 0 else max(1, len(similarities) - 1)

    # 1. Temporal Smoothing (Ignore rapid biometric drops)
    smoothed_sims = medfilt(similarities, kernel_size=kernel_size)
    
    # 2. Absolute Binarization (Hard Gate)
    # If it is above threshold, it is EXACTLY 1.0. If below, EXACTLY 0.0.
    binary_mask = (smoothed_sims > base_threshold).astype(np.float32)
    
    # 3. Convolutional Crossfade (Anti-Click)
    # Calculate how many frames represent crossfade_ms
    fade_frames = max(3, int((crossfade_ms / 1000.0) * fps))
    
    # Create a uniform moving average kernel
    kernel = np.ones(fade_frames, dtype=np.float32) / fade_frames
    
    # Convolve the binary mask with the kernel to create a perfect linear glide
    # only at the exact boundaries between 1.0 and 0.0.
    final_mask = np.convolve(binary_mask, kernel, mode='same')
    
    # 4. Enforce strict floating-point bounds just in case of float drift
    final_mask = np.clip(final_mask, 0.0, 1.0)
    
    return final_mask


def merge_intervals(intervals: list[dict]) -> list[dict]:
    """Merges overlapping or touching time dictionaries."""
    if not intervals: 
        return []
    sorted_int = sorted(intervals, key=lambda x: x["start"])
    merged = [sorted_int[0]]
    for current in sorted_int[1:]:
        previous = merged[-1]
        if current["start"] <= previous["end"]:
            previous["end"] = max(previous["end"], current["end"])
        else:
            merged.append(current)
    return merged


def smooth_and_merge_purged_turns(turns_list: list[dict], head_pad: float = 3.0, tail_pad: float = 4.0) -> list[dict]:
    """Applies asymmetrical padding (3.0s head, 4.0s tail) to capture soft opening breaths/phrases and sustained final vowels."""
    if not turns_list:
        return []
    padded_turns = []
    for turn in turns_list:
        padded_turns.append({
            "start": max(0.0, turn["start"] - head_pad),
            "end": turn["end"] + tail_pad
        })
    padded_turns.sort(key=lambda x: x["start"])
    merged_turns = [padded_turns[0]]
    for current in padded_turns[1:]:
        previous = merged_turns[-1]
        if current["start"] <= previous["end"]:
            previous["end"] = max(previous["end"], current["end"])
        else:
            merged_turns.append(current)
    return merged_turns


def subtract_purged_from_primary(primary_turns: list[dict], purged_turns: list[dict]) -> list[dict]:
    """Strictly subtracts time intervals claimed by purged_turns from primary_turns.
    Ensures Quran/music tails never bleed into the AI translation track."""
    cleaned_primary = []
    for p_turn in primary_turns:
        p_start, p_end = p_turn["start"], p_turn["end"]
        current_intervals = [(p_start, p_end)]
        
        for q_turn in purged_turns:
            q_start, q_end = q_turn["start"], q_turn["end"]
            next_intervals = []
            
            for start, end in current_intervals:
                # No overlap
                if end <= q_start or start >= q_end:
                    next_intervals.append((start, end))
                else:
                    # Overlap on left
                    if start < q_start:
                        next_intervals.append((start, q_start))
                    # Overlap on right
                    if end > q_end:
                        next_intervals.append((q_end, end))
                        
            current_intervals = next_intervals
            
        for start, end in current_intervals:
            cleaned_primary.append({"start": start, "end": end})
                
    return cleaned_primary


def execute_acoustic_routing(vocal_stem_path: str):
    """Clean Stage 2 Routing:
    1. CNN Classification (inaSpeechSegmenter)
    2. Asymmetrical Padding (3.0s Head / 4.0s Tail)
    3. Terminal Outro Snap
    4. Interval Subtraction & Micro-Gap Purge (< 1.5s)
    """
    logger.info("[STAGE 2] Running Clean Acoustic Structural Router...")
    try:
        from inaSpeechSegmenter import Segmenter
        seg = Segmenter(vad_engine='smn', detect_gender=False)
        segmentation = seg(vocal_stem_path)
        audio_duration = float(segmentation[-1][2]) if segmentation else 0.0
    except Exception as err:
        logger.warning(f"[STAGE 2] Segmenter error: {err}")
        segmentation = []
        audio_duration = 0.0

    raw_primary_turns = []
    raw_purged_turns = []

    for label, start, end in segmentation:
        turn_dict = {"start": float(start), "end": float(end)}
        if label == 'speech':
            raw_primary_turns.append(turn_dict)
        elif label == 'music':
            raw_purged_turns.append(turn_dict)
            
    # 1. Asymmetrical Padding (3.0s Head, 4.0s Tail)
    final_purged_turns = smooth_and_merge_purged_turns(raw_purged_turns, head_pad=3.0, tail_pad=4.0)

    # 2. Terminal Outro Snap
    if final_purged_turns and audio_duration > 0.0:
        last_purged = final_purged_turns[-1]
        if last_purged["end"] >= (audio_duration - 20.0):
            logger.info("[STAGE 2] Outro detected. Snapping tail to end of file.")
            last_purged["end"] = audio_duration + 5.0 
            
    # 3. Interval Subtraction
    final_primary_turns = subtract_purged_from_primary(raw_primary_turns, final_purged_turns)

    # 4. Micro-Gap Cleanup (Drop only sub-200ms acoustic glitches)
    final_primary_turns = [t for t in final_primary_turns if (t["end"] - t["start"]) > 0.2]

    logger.info(f"[STAGE 2 COMPLETE] Speech turns: {len(final_primary_turns)} | Purged turns: {len(final_purged_turns)}")

    return final_primary_turns, final_purged_turns


def perform_target_speaker_extraction(
    voc_wav_path: str,
    host_ref_path: str = None,
    pristine_host_output_path: str = None,
    purged_secondary_output_path: str = None,
    window_sec: float = 1.0,
    hop_sec: float = 0.2,
    sim_threshold: float = 0.35,
    fade_ms: int = 50,
    hf_auth_token: str = None
) -> tuple[str, str]:
    """
    Backwards compatibility alias for process_vcta_acoustic_routing_and_restoration.
    """
    return process_vcta_acoustic_routing_and_restoration(
        voc_wav_path=voc_wav_path,
        pristine_host_output_path=pristine_host_output_path,
        purged_secondary_output_path=purged_secondary_output_path,
        window_sec=window_sec,
        hop_sec=hop_sec,
        sim_threshold=sim_threshold,
        fade_ms=fade_ms,
        hf_auth_token=hf_auth_token
    )


def process_vcta_acoustic_routing_and_restoration(
    voc_wav_path: str,
    pristine_host_output_path: str,
    purged_secondary_output_path: str,
    window_sec: float = 1.0,
    hop_sec: float = 0.2,
    sim_threshold: float = 0.35,
    fade_ms: int = 50,
    hf_auth_token: str = None
) -> tuple[str, str]:
    """
    Stage 3: Acoustic Structural Routing (Architecture V9.3).
    Uses CNN Melodic Radar + Contact Override + Energy-Legitimacy Gate.
    """
    logger.info("[ACOUSTIC ROUTER] Loading audio stem for Acoustic Structural Routing...")
    voc_audio, sr = sf.read(voc_wav_path, dtype='float32')
    num_samples = len(voc_audio)

    primary_turns, purged_turns = execute_acoustic_routing(voc_wav_path)

    host_mask = np.ones(num_samples, dtype='float32')
    sec_mask = np.zeros(num_samples, dtype='float32')

    if purged_turns:
        for turn in purged_turns:
            s_idx = max(0, int(turn["start"] * sr))
            e_idx = min(num_samples, int(turn["end"] * sr))
            sec_mask[s_idx:e_idx] = 1.0

        fade_samples = int((fade_ms / 1000.0) * sr)
        if fade_samples > 1:
            kernel = np.hanning(fade_samples * 2)
            kernel = kernel / (np.sum(kernel) + 1e-9)
            sec_mask = np.clip(np.convolve(sec_mask, kernel, mode='same'), 0.0, 1.0)
            
        host_mask = np.clip(1.0 - sec_mask, 0.0, 1.0)
    else:
        host_mask = np.ones(num_samples, dtype='float32')
        sec_mask = np.zeros(num_samples, dtype='float32')

    if voc_audio.ndim > 1:
        host_mask_expanded = host_mask[:, None]
        sec_mask_expanded = sec_mask[:, None]
    else:
        host_mask_expanded = host_mask
        sec_mask_expanded = sec_mask

    pristine_host = voc_audio * host_mask_expanded
    purged_secondary = voc_audio * sec_mask_expanded

    sf.write(pristine_host_output_path, pristine_host, sr, subtype='FLOAT')
    sf.write(purged_secondary_output_path, purged_secondary, sr, subtype='FLOAT')

    logger.info(
        f"[TSE Complete]\n"
        f"  Pristine Host Vocals saved to     : {pristine_host_output_path}\n"
        f"  Purged Secondary Audio saved to  : {purged_secondary_output_path}"
    )
    return pristine_host_output_path, purged_secondary_output_path


def mix_secondary_into_background(
    instrumental_path: str,
    purged_secondary_path: str,
    output_restored_bg_path: str,
    rms_threshold_db: float = -35.0,
    min_active_sec: float = 1.0
) -> str:
    """
    Stage 4 Mixdown: Mixes purged secondary audio (Quran/songs/padded audio)
    blindly into the background stem without running RMS or energy gates.
    Stage 3 already calculated exact routing; Stage 4 blindly sums the tracks.
    """
    logger.info("[TSE Step 3] Mixing purged secondary audio directly into background stem...")
    bg_audio, sr = sf.read(instrumental_path, dtype='float32')
    sec_audio, _ = sf.read(purged_secondary_path, dtype='float32')

    min_len = min(len(bg_audio), len(sec_audio))
    bg_audio = bg_audio[:min_len]
    sec_audio = sec_audio[:min_len]

    restored_bg = bg_audio + sec_audio
    restored_bg = np.clip(restored_bg, -1.0, 1.0)

    sf.write(output_restored_bg_path, restored_bg, sr, subtype='FLOAT')
    logger.info(f"[TSE Step 3 Complete] Saved background stem to: {output_restored_bg_path}")
    return output_restored_bg_path
