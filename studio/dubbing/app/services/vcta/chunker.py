import os
import uuid
import asyncio
import contextlib
import torch
import numpy as np
import scipy.io.wavfile as wavfile
import librosa
import logging
import gc

logger = logging.getLogger(__name__)


@contextlib.contextmanager
def _trusted_torch_load():
    """Patch torch.load to allow pickle weights (Pyannote) only for the duration
    of the with-block. PyTorch since 2.6 defaults to weights_only=True; Pyannote
    checkpoints use legitimate pickle format. Restores on exit. See
    handoffs/dubbing-security-pass3-fixes.md Fix 3."""
    _original = torch.load
    def _patched(*args, **kwargs):
        kwargs["weights_only"] = False
        return _original(*args, **kwargs)
    torch.load = _patched
    try:
        yield
    finally:
        torch.load = _original

# Initialize Pyannote pipeline lazily
_pipeline = None

def calculate_rms_energy(file_path: str) -> float:
    """Calculates the raw RMS energy of an audio file."""
    try:
        import soundfile as sf
        data, _ = sf.read(file_path, dtype='float32')
        if len(data) == 0:
            return 0.0
        if len(data.shape) > 1:
            data = data.mean(axis=1)
        return float(np.sqrt(np.mean(data**2) + 1e-10))
    except Exception as e:
        logger.error(f"[CHUNKER] Failed to calculate RMS for {file_path}: {e}")
        return 0.0

def get_pyannote_pipeline():
    global _pipeline
    if _pipeline is None:
        token = os.environ.get("HF_TOKEN")
        if not token or token == "replace_me":
            logger.warning("[CHUNKER] HF_TOKEN is missing or not set. Pyannote speaker diarization will fail.")
            return None
            
        try:
            import numpy as np
            if not hasattr(np, "NaN"):
                np.NaN = np.nan
            if not hasattr(np, "NAN"):
                np.NAN = np.nan

            import huggingface_hub
            if getattr(huggingface_hub, "_patched_for_pyannote", None) is None:
                huggingface_hub._patched_for_pyannote = True
                funcs_to_patch = ["hf_hub_download", "snapshot_download"]
                for func_name in funcs_to_patch:
                    if hasattr(huggingface_hub, func_name):
                        orig = getattr(huggingface_hub, func_name)
                        def make_patched(original_func):
                            def _patched(*args, **kwargs):
                                if "use_auth_token" in kwargs:
                                    kwargs["token"] = kwargs.pop("use_auth_token")
                                return original_func(*args, **kwargs)
                            return _patched
                        setattr(huggingface_hub, func_name, make_patched(orig))
                
                # ModelCard.load also gets called
                if hasattr(huggingface_hub, "ModelCard") and hasattr(huggingface_hub.ModelCard, "load"):
                    orig_load = huggingface_hub.ModelCard.load
                    @classmethod
                    def _patched_load(cls, *args, **kwargs):
                        if "use_auth_token" in kwargs:
                            kwargs["token"] = kwargs.pop("use_auth_token")
                        return orig_load.__func__(cls, *args, **kwargs)
                    huggingface_hub.ModelCard.load = _patched_load

            import torchaudio
            if not hasattr(torchaudio, "set_audio_backend"):
                torchaudio.set_audio_backend = lambda x: None
            from pyannote.audio import Pipeline
            with _trusted_torch_load():
                logger.info("[CHUNKER] Loading pyannote/speaker-diarization-3.1...")
                _pipeline = Pipeline.from_pretrained(
                    "pyannote/speaker-diarization-3.1",
                    use_auth_token=token
                )
            
            # MANDATE: Override default VAD threshold
            try:
                _pipeline.instantiate({
                    "segmentation": {
                        "min_duration_off": 0.250,
                        "min_duration_on": 0.105
                    }
                })
            except Exception as e:
                logger.warning(f"[CHUNKER] Could not instantiate Pyannote params: {e}")
                
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            _pipeline.to(device)
            logger.info("[CHUNKER] Pyannote loaded successfully.")
        except Exception as e:
            logger.error("[CHUNKER] Failed to load Pyannote pipeline: %s", e)
            return None
    return _pipeline

def _find_silence_split(data: np.ndarray, sample_rate: int) -> int:
    """Find absolute silence (RMS < -60dB) for > 500ms to split the audio."""
    # -60dB is approx 0.001 amplitude
    threshold = 0.001
    min_silence_samples = int(0.525 * sample_rate)
    
    # Calculate rolling RMS energy
    window_size = int(0.1 * sample_rate) # 100ms windows
    
    # Simple search: look for a continuous block of low amplitude near the middle
    midpoint = len(data) // 2
    search_radius = len(data) // 4
    
    start_search = max(0, midpoint - search_radius)
    end_search = min(len(data), midpoint + search_radius)
    
    current_silence = 0
    best_split = -1
    
    for i in range(start_search, end_search, window_size):
        chunk = data[i:i+window_size]
        rms = np.sqrt(np.mean(chunk**2) + 1e-10)
        
        if rms < threshold:
            current_silence += window_size
            if current_silence >= min_silence_samples:
                best_split = i - (current_silence // 2)
                break
        else:
            current_silence = 0
            
    return best_split

def _slice_long_turn(turn: dict, audio_data: np.ndarray, sample_rate: int) -> list[dict]:
    s = turn["start"]
    e = turn["end"]
    spk = turn["speaker"]
    
    if (e - s) <= 15.0:
        return [turn]
        
    sub_turns = []
    current_start = s
    
    threshold = 0.001
    window_samples = int(0.05 * sample_rate) # 50ms window
    
    while (e - current_start) > 15.0:
        split_time = -1.0
        
        # 1. Search between 15s and 30s for a 300ms pause
        search_start = current_start + 15.0
        search_end = min(current_start + 30.0, e)
        
        if search_end > search_start:
            start_idx = int(search_start * sample_rate)
            end_idx = int(search_end * sample_rate)
            
            # Step 1A: Look for 300ms pause in [15s, 30s]
            target_silence_samples = int(0.3 * sample_rate) # 300ms
            current_silence = 0
            
            for i in range(start_idx, end_idx - window_samples, window_samples):
                chunk = audio_data[i:i+window_samples]
                rms = np.sqrt(np.mean(chunk**2) + 1e-10)
                if rms < threshold:
                    current_silence += window_samples
                    if current_silence >= target_silence_samples:
                        split_time = (i - (current_silence // 2)) / sample_rate
                        break
                else:
                    current_silence = 0
                    
            # Step 1B: If no 300ms pause found, search the SAME [15s, 30s] window for a 200ms pause
            if split_time == -1.0:
                target_silence_samples = int(0.2 * sample_rate) # 200ms
                current_silence = 0
                for i in range(start_idx, end_idx - window_samples, window_samples):
                    chunk = audio_data[i:i+window_samples]
                    rms = np.sqrt(np.mean(chunk**2) + 1e-10)
                    if rms < threshold:
                        current_silence += window_samples
                        if current_silence >= target_silence_samples:
                            split_time = (i - (current_silence // 2)) / sample_rate
                            break
                    else:
                        current_silence = 0
                        
        # 3. Fallback: If no pause found at all in [15s, 30s], force hard split at 30.0s max
        if split_time == -1.0:
            split_time = min(current_start + 30.0, e)
            
        sub_turns.append({"start": current_start, "end": split_time, "speaker": spk})
        current_start = split_time
        
    if (e - current_start) >= 0.5:
        sub_turns.append({"start": current_start, "end": e, "speaker": spk})
        
    return sub_turns

def find_best_silence_split(audio_data: np.ndarray, sample_rate: int, search_start: float, search_end: float) -> float:
    """
    Scans audio waveform BACKWARD from search_end (30.0s) down to search_start (15.0s) 
    using the Progressive Silence Ladder:
      1. Scan backward for 200ms pause (RMS < -60dB)
      2. Scan backward for 150ms pause
      3. Scan backward for 100ms pause
      4. Scan backward for 50ms pause
      5. Fallback: Absolute lowest RMS energy point (quietest breath 50ms window)
    """
    if len(audio_data) == 0:
        return (search_start + search_end) / 2.0
        
    start_idx = max(0, int(search_start * sample_rate))
    end_idx = min(len(audio_data), int(search_end * sample_rate))
    
    if start_idx >= end_idx:
        return (search_start + search_end) / 2.0
        
    window_samples = int(0.05 * sample_rate) # 50ms window
    step_samples = int(0.01 * sample_rate)   # 10ms step
    threshold = 0.001 # -60dB

    # Progressive Silence Ladder (Scanning Backward: 300ms -> 250ms -> 200ms -> 150ms -> 100ms -> 50ms)
    pause_targets_ms = [300, 250, 200, 150, 100, 50]
    
    for target_ms in pause_targets_ms:
        target_samples = int((target_ms / 1000.0) * sample_rate)
        current_silence = 0
        for i in range(end_idx - window_samples, start_idx, -step_samples):
            chunk = audio_data[i : i + window_samples]
            rms = np.sqrt(np.mean(chunk**2) + 1e-10)
            if rms < threshold:
                current_silence += step_samples
                if current_silence >= target_samples:
                    return (i + (current_silence // 2)) / sample_rate
            else:
                current_silence = 0

    # Fallback: Find absolute lowest RMS energy point (scanning backward)
    min_rms = float('inf')
    best_time = (search_start + search_end) / 2.0
    for i in range(end_idx - window_samples, start_idx, -step_samples):
        chunk = audio_data[i : i + window_samples]
        rms = np.sqrt(np.mean(chunk**2) + 1e-10)
        if rms < min_rms:
            min_rms = rms
            best_time = (i + window_samples // 2) / sample_rate
            
    return best_time

# Alias for backward compatibility
find_optimal_split_point = find_best_silence_split


def segment_audio_pause_first(
    audio_data: np.ndarray,
    sample_rate: int,
    min_dur: float = 0.0,
    max_dur: float = 10.0,
    silence_thresh_db: float = -38.0,
    min_pause_sec: float = 0.25
) -> list[dict]:
    """
    Pause-First Natural Speech Segmentation (Zero-Min Duration):
    Detects real physical acoustic pauses (>=250ms silence) and cuts strictly at every natural
    pause/breath boundary. If a user says one single word (e.g. 1 second) and pauses, it creates
    a dedicated chunk right there without requiring arbitrary minimum durations.
    """
    total_sec = len(audio_data) / sample_rate
    frame_len = int(0.020 * sample_rate)  # 20ms frame
    num_frames = len(audio_data) // frame_len
    
    # 1. Compute frame RMS & dB
    times = []
    db_list = []
    for i in range(num_frames):
        frame = audio_data[i * frame_len : (i + 1) * frame_len]
        rms = np.sqrt(np.mean(frame**2) + 1e-10)
        db = 20 * np.log10(max(rms, 1e-5))
        times.append(i * frame_len / sample_rate)
        db_list.append(db)
        
    # 2. Detect all physical pauses >= min_pause_sec
    pauses = []
    in_pause = False
    p_start = 0.0
    for t, db in zip(times, db_list):
        if db < silence_thresh_db:
            if not in_pause:
                in_pause = True
                p_start = t
        else:
            if in_pause:
                in_pause = False
                dur = t - p_start
                if dur >= min_pause_sec:
                    pauses.append((p_start, t, dur))
    if in_pause:
        pauses.append((p_start, total_sec, total_sec - p_start))
        
    # 3. Build chunks by splitting at every natural pause boundary
    chunks = []
    cur_start = 0.0
    
    while cur_start < (total_sec - 0.25):
        # Look for the next pause that starts after cur_start + 0.35s (at least 1 spoken word)
        # and within the max_dur window
        valid_pauses = [p for p in pauses if p[0] >= (cur_start + 0.35) and (p[0] - cur_start) <= max_dur]
        
        if valid_pauses:
            # Pick the earliest pause to slice cleanly right after the word/phrase
            best_p = valid_pauses[0]
            split_time = (best_p[0] + best_p[1]) / 2.0
        else:
            # If no pause within max_dur:
            if (total_sec - cur_start) <= max_dur:
                split_time = total_sec
            else:
                # Search for lowest energy valley within window
                split_time = find_best_silence_split(
                    audio_data=audio_data,
                    sample_rate=sample_rate,
                    search_start=cur_start + 3.0,
                    search_end=cur_start + max_dur
                )
                
        dur = round(split_time - cur_start, 3)
        if dur >= 0.3:  # Only add valid spoken segments (>300ms)
            chunks.append({
                "start": round(cur_start, 3),
                "end": round(split_time, 3),
                "duration": dur,
                "speaker": "SPEAKER_00"
            })
        cur_start = split_time
        
    return chunks


def enforce_minimum_chunk_duration(
    turns: list[dict],
    audio_data: np.ndarray,
    sample_rate: int,
    min_dur: float = 3.5,
    max_dur: float = 10.0
) -> list[dict]:
    """
    Guarantees natural pause-first speech segmentation across all turns.
    """
    if not turns:
        return []
        
    return segment_audio_pause_first(
        audio_data=audio_data,
        sample_rate=sample_rate,
        min_dur=min_dur,
        max_dur=max_dur
    )


def find_first_silence_valley(
    audio_data: np.ndarray,
    sr: int,
    search_start_sec: float,
    search_end_sec: float,
    silence_threshold: float = 0.045
) -> float:
    """
    Scans forward from search_start_sec to find the FIRST silence valley
    immediately after Speaker 1 finishes.
    This guarantees that the cut point sits in the inter-speaker pause, 
    so Speaker 2's first word is NEVER cut in half.
    """
    s_sample = max(0, int(search_start_sec * sr))
    e_sample = min(len(audio_data), int(search_end_sec * sr))
    if e_sample <= s_sample + int(0.05 * sr):
        return search_start_sec

    sub = audio_data[s_sample:e_sample]
    frame_len = int(0.025 * sr)
    hop_len = int(0.010 * sr)
    
    if len(sub) < frame_len:
        return search_start_sec
        
    try:
        rms = librosa.feature.rms(y=sub, frame_length=frame_len, hop_length=hop_len)[0]
        times = search_start_sec + librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=hop_len)
        
        below_thresh_indices = np.where(rms <= silence_threshold)[0]
        if len(below_thresh_indices) > 0:
            first_silence_group = []
            for idx in below_thresh_indices:
                if not first_silence_group or idx == first_silence_group[-1] + 1:
                    first_silence_group.append(idx)
                else:
                    break # End of the first inter-speaker silence gap
                    
            best_idx = first_silence_group[int(np.argmin(rms[first_silence_group]))]
            return round(float(times[best_idx]), 3)

        half_len = max(1, len(rms) // 2)
        min_idx = int(np.argmin(rms[:half_len]))
        return round(float(times[min_idx]), 3)
    except Exception:
        return search_start_sec


def split_turns_on_overlap_boundaries(
    turns: list[dict],
    overlap_intervals: list[dict],
    audio_data: np.ndarray = None,
    sample_rate: int = 16000
) -> list[dict]:
    """
    Stage 3 (v2 Architecture): Splits speech turns at overlap onset (start) and offset (end)
    timestamps refined by acoustic micro-silence energy dips.
    Preserves all speakers neutrally without dropping or biased filtering.
    """
    if not overlap_intervals:
        for t in turns:
            t["has_overlap"] = False
        return turns

    split_chunks = []
    for turn in turns:
        t_start = turn["start"]
        t_end = turn["end"]
        spk = turn.get("speaker", "SPEAKER_00")

        # Find all cuts within [t_start, t_end]
        cut_points = {t_start, t_end}
        for o in overlap_intervals:
            o_s, o_e = o["start"], o["end"]
            
            # Snap cut points to acoustic energy dips if audio is available
            if audio_data is not None:
                o_s = find_first_silence_valley(audio_data, sample_rate, max(0, o_s - 0.2), o_s + 0.3)
                o_e = find_first_silence_valley(audio_data, sample_rate, max(0, o_e - 0.2), o_e + 0.3)

            if t_start + 0.15 < o_s < t_end - 0.15:
                cut_points.add(o_s)
            if t_start + 0.15 < o_e < t_end - 0.15:
                cut_points.add(o_e)

        sorted_cuts = sorted(list(cut_points))

        for i in range(len(sorted_cuts) - 1):
            sub_s = sorted_cuts[i]
            sub_e = sorted_cuts[i+1]
            dur = round(sub_e - sub_s, 3)

            if dur < 0.25:
                continue

            # Check if midpoint falls inside any overlap interval
            mid = (sub_s + sub_e) / 2.0
            is_overlap = any(o["start"] <= mid <= o["end"] for o in overlap_intervals)

            split_chunks.append({
                "start": round(sub_s, 3),
                "end": round(sub_e, 3),
                "duration": dur,
                "speaker": spk,
                "has_overlap": is_overlap
            })

    return split_chunks


def resolve_short_overlap_transitions(
    turns: list[dict],
    audio_data: np.ndarray,
    sr: int = 16000,
    max_transition_sec: float = 1.8
) -> list[dict]:
    """
    When two consecutive speaker turns have a short overlap (<= 1.8s),
    finds the exact first silence valley between the speakers and cleanly hands off
    from Speaker 1 to Speaker 2. This prevents splitting Speaker 2's words in half.
    """
    if len(turns) < 2:
        return turns

    sorted_turns = sorted(turns, key=lambda x: x["start"])
    resolved = []
    
    i = 0
    while i < len(sorted_turns):
        cur = sorted_turns[i].copy()
        
        if i + 1 < len(sorted_turns):
            nxt = sorted_turns[i + 1].copy()
            
            # Check if there is an overlap between cur and nxt
            if nxt["start"] < cur["end"]:
                overlap_dur = cur["end"] - nxt["start"]
                
                if overlap_dur <= max_transition_sec:
                    # Tri-Metric Physical Boundary Decision (MFCC Vocal Tract Delta + F0 Pitch Discontinuity + Silero VAD)
                    try:
                        from app.services.vcta.acoustic_boundary_matrix import find_optimal_physical_boundary
                        split_t = find_optimal_physical_boundary(
                            audio_data=audio_data,
                            sr=sr,
                            search_start_sec=nxt["start"],
                            search_end_sec=cur["end"]
                        )
                        logger.info(
                            f"[SURGICAL-LOG] Transition Detected between {cur.get('speaker')} & {nxt.get('speaker')}: "
                            f"Window [{nxt['start']:.2f}s -> {cur['end']:.2f}s] (overlap={overlap_dur:.2f}s) "
                            f"==> Physical Cut Locked at: {split_t:.3f}s (MFCC/F0/Silero-VAD)"
                        )
                    except Exception as e:
                        logger.warning(f"[CHUNKER] Tri-metric boundary fallback: {e}")
                        split_t = find_first_silence_valley(
                            audio_data=audio_data,
                            sr=sr,
                            search_start_sec=nxt["start"],
                            search_end_sec=cur["end"],
                            silence_threshold=0.045
                        )
                        logger.info(f"[SURGICAL-LOG] Silence Valley Fallback Cut at: {split_t:.3f}s")
                    
                    # Clean handoff: cur ends at split_t, nxt starts at split_t
                    prev_end = cur["end"]
                    cur["end"] = split_t
                    cur["duration"] = round(cur["end"] - cur["start"], 3)
                    cur["has_overlap"] = False
                    
                    prev_nxt_start = nxt["start"]
                    nxt["start"] = split_t
                    nxt["duration"] = round(nxt["end"] - nxt["start"], 3)
                    nxt["has_overlap"] = False
                    
                    logger.info(
                        f"[CHUNK-DIAGNOSTIC] Left Chunk [{cur.get('speaker')}]: {cur['start']:.2f}s -> {cur['end']:.2f}s ({cur['duration']:.2f}s) | "
                        f"Right Chunk [{nxt.get('speaker')}]: {nxt['start']:.2f}s -> {nxt['end']:.2f}s ({nxt['duration']:.2f}s)"
                    )
                    
                    if cur["duration"] >= 0.25:
                        resolved.append(cur)
                    sorted_turns[i + 1] = nxt
                    i += 1
                    continue

        if cur.get("duration", cur["end"] - cur["start"]) >= 0.25:
            cur["duration"] = round(cur["end"] - cur["start"], 3)
            cur["has_overlap"] = cur.get("has_overlap", False)
            resolved.append(cur)
            logger.info(f"[CHUNK-DIAGNOSTIC] Finalized Chunk [{cur.get('speaker')}]: {cur['start']:.2f}s -> {cur['end']:.2f}s ({cur['duration']:.2f}s)")
        i += 1

    return resolved


async def run_diarization(audio_path: str) -> tuple[list[dict], list[dict]]:
    """
    Stage 2-4: Acoustic Diarization & Collision Surgery (v2 Architecture).
    Returns finalized chunk objects with has_overlap flags and overlap intervals.
    """
    def _diarize():
        pipeline = get_pyannote_pipeline()
        if not pipeline:
            raise Exception("Our voice separation service is currently undergoing maintenance. Please try again shortly.")
            
        import soundfile as sf
        audio_info = sf.info(audio_path)
        total_duration = audio_info.duration
        
        logger.info(f"[CHUNKER] STAGE 1: Analyzing {audio_path} (Duration: {total_duration:.2f}s)")
        
        audio_data, sample_rate = sf.read(audio_path, dtype='float32')
        if len(audio_data.shape) > 1:
            audio_data = audio_data.mean(axis=1)

        logger.info(f"[CHUNKER] STAGE 2: Running Pyannote 3.1 Powerset Diarization...")
        diarization = pipeline(audio_path, min_speakers=1, max_speakers=5)

        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        # Extract native Pyannote 3.1 powerset overlap timeline
        overlap_intervals = []
        try:
            overlap_timeline = diarization.get_timeline().get_overlap()
            for seg in overlap_timeline:
                overlap_intervals.append({
                    "start": round(seg.start, 2),
                    "end": round(seg.end, 2),
                    "duration": round(seg.end - seg.start, 2)
                })
            logger.info(f"[CHUNKER] STAGE 2: Detected {len(overlap_intervals)} native powerset overlap regions.")
        except Exception as e:
            logger.warning(f"[CHUNKER] Powerset overlap extraction warning: {e}")

        speakers_found = list(diarization.itertracks(yield_label=True))
        raw_turns = [{"start": t.start, "end": t.end, "speaker": l} for t, _, l in speakers_found]

        # STAGE 3: Map Pyannote's native global speaker IDs by duration (Speaker_A = Main Host)
        speaker_durations = {}
        for t in raw_turns:
            dur = t["end"] - t["start"]
            speaker_durations[t["speaker"]] = speaker_durations.get(t["speaker"], 0.0) + dur

        sorted_spks = sorted(speaker_durations.keys(), key=lambda k: -speaker_durations[k])
        label_map = {spk: f"Speaker_{chr(65 + idx)}" for idx, spk in enumerate(sorted_spks)}

        for t in raw_turns:
            t["speaker"] = label_map.get(t["speaker"], t["speaker"])
            t["global_speaker_id"] = t["speaker"]

        logger.info(f"[CHUNKER] Pyannote Native Global Speakers ({len(sorted_spks)} total):")
        for spk in sorted_spks:
            logger.info(f"  * {label_map[spk]} ({spk}): {speaker_durations[spk]:.2f}s total speech")

        # STAGE 4: Resolve short transitions with acoustic boundary snapping (Tri-Metric / Silence Scalpel)
        logger.info("[CHUNKER] STAGE 4: Resolving transitions with physical boundary matrix...")
        resolved_turns = resolve_short_overlap_transitions(raw_turns, audio_data, sr=sample_rate)

        # Filter out micro-noise glitches under 0.25s
        valid_turns = [t for t in resolved_turns if (t["end"] - t["start"]) >= 0.25]
        valid_turns.sort(key=lambda x: x["start"])

        logger.info(f"[CHUNKER] Successfully produced {len(valid_turns)} cleanly resolved multi-speaker sub-chunks.")
        return valid_turns, overlap_intervals

    return await asyncio.to_thread(_diarize)
