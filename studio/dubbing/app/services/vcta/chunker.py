import os
import uuid
import asyncio
import contextlib
import torch
import numpy as np
import scipy.io.wavfile as wavfile
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
    min_pause_sec: float = 0.40
) -> list[dict]:
    """
    Pause-First Natural Speech Segmentation (Zero-Min Duration):
    Detects real physical acoustic pauses (>=400ms silence) and cuts strictly at every natural
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


async def run_diarization(audio_path: str) -> tuple[list[dict], list[dict]]:
    """
    Stage 2-4: Acoustic Diarization & Collision Surgery.
    Returns the exact finalized chunk objects ready for FFmpeg slicing, 
    and a list of purged background secondary speaker turns for restoration.
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

        if total_duration > 1800:
            logger.warning("[CHUNKER] Audio exceeds 30 minutes! Attempting to find silence split...")
                
            split_idx = _find_silence_split(audio_data, sample_rate)
            if split_idx > 0:
                logger.info(f"[CHUNKER] Found silence split at {split_idx/sample_rate:.2f}s. OOM guard triggered.")
                audio_data = audio_data[:split_idx]
                waveform = torch.from_numpy(np.ascontiguousarray(audio_data)).float().unsqueeze(0)
                logger.info(f"[CHUNKER] STAGE 2: Running Pyannote 3.1 on preloaded tensor...")
                diarization = pipeline({"waveform": waveform, "sample_rate": sample_rate}, min_speakers=1, max_speakers=5)
                del waveform
            else:
                raise Exception("This video is too long without any natural pauses. Please cut the video into smaller segments and try again.")
        else:
            # Native Pyannote loading avoids C++ memory access violations on Windows
            logger.info(f"[CHUNKER] STAGE 2: Running Pyannote 3.1 natively on file path...")
            diarization = pipeline(audio_path, min_speakers=1, max_speakers=5)
        
        # Memory Release per v4.0 spec
        if 'waveform' in locals():
            del waveform
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        
        speakers_found = list(diarization.itertracks(yield_label=True))
        
        raw_turns = [{"start": t.start, "end": t.end, "speaker": l} for t, _, l in speakers_found]
        
        logger.info(f"[CHUNKER] Pre-processing {len(raw_turns)} raw turns for >30.0s overflow...")
        sliced_turns = []
        for t in raw_turns:
            sliced_turns.extend(_slice_long_turn(t, audio_data, sample_rate))
        raw_turns = sliced_turns
        logger.info(f"[CHUNKER] STAGE 2.5: Primary Speaker Filtering (V2.4)")
        speaker_durations = {}
        for t in raw_turns:
            spk = t["speaker"]
            dur = t["end"] - t["start"]
            speaker_durations[spk] = speaker_durations.get(spk, 0.0) + dur
            
        if speaker_durations:
            valid_speakers = [spk for spk, dur in speaker_durations.items() if dur >= 5.0]
            if valid_speakers:
                earliest_starts = {}
                for t in raw_turns:
                    spk = t["speaker"]
                    if spk in valid_speakers and spk not in earliest_starts:
                        earliest_starts[spk] = t["start"]
                primary_speaker = min(earliest_starts, key=earliest_starts.get)
            else:
                primary_speaker = max(speaker_durations, key=speaker_durations.get)
                
            logger.info(f"[CHUNKER] Primary Speaker detected: {primary_speaker} with {speaker_durations[primary_speaker]:.2f}s total duration.")
            
            primary_raw_turns = [t for t in raw_turns if t["speaker"] == primary_speaker]
            primary_raw_turns.sort(key=lambda x: x["start"])
            
            purged_turns = []
            current_time = 0.0
            for t in primary_raw_turns:
                if t["start"] > current_time:
                    purged_turns.append({"start": current_time, "end": t["start"]})
                current_time = max(current_time, t["end"])
                
            if current_time < total_duration:
                purged_turns.append({"start": current_time, "end": total_duration})
                
            raw_turns = primary_raw_turns
            logger.info(f"[CHUNKER] Extracted {len(purged_turns)} gaps (Inverse Timeline) for Restoration. Kept {len(raw_turns)} primary chunks.")
        else:
            purged_turns = []
            logger.warning("[CHUNKER] No speakers found during diarization!")
        
        logger.info(f"[CHUNKER] STAGE 3: Timeline Merging (Strict Adjacency)")
        raw_turns.sort(key=lambda x: x["start"])
        
        merged_turns = raw_turns.copy()
        previous_length = -1
        max_iterations = len(merged_turns)
        iterations = 0
        
        while len(merged_turns) != previous_length:
            if iterations > max_iterations:
                raise Exception("An unexpected system error occurred while processing the audio timeline. Please try again or contact support.")
            iterations += 1
            previous_length = len(merged_turns)
            
            new_merged = []
            skip = False
            for i in range(len(merged_turns)):
                if skip:
                    skip = False
                    continue
                if i < len(merged_turns) - 1:
                    turn_a = merged_turns[i]
                    turn_b = merged_turns[i+1]
                    
                    should_merge = False
                    if turn_a["speaker"] == turn_b["speaker"]:
                        potential_duration = max(turn_a["end"], turn_b["end"]) - turn_a["start"]
                        gap = turn_b["start"] - turn_a["end"]
                        
                        # Progressive Silence Window Matrix
                        if potential_duration < 15.0:
                            # ALWAYS accumulate under 15 seconds (NO cuts under 15s)
                            should_merge = True
                        elif potential_duration <= 30.0:
                            # 15s to 30s window: cut if silence is >= 0.2s (200ms)
                            if gap >= 0.2:
                                should_merge = False
                            else:
                                should_merge = True
                        else:
                            # > 30.0s window: HARD CAP (never merge past 30 seconds)
                            should_merge = False

                    if should_merge:
                        potential_end = max(turn_a["end"], turn_b["end"])
                        merged = {"start": turn_a["start"], "end": potential_end, "speaker": turn_a["speaker"]}
                        new_merged.append(merged)
                        skip = True
                    else:
                        new_merged.append(turn_a)
                else:
                    new_merged.append(merged_turns[i])
            merged_turns = new_merged

        # Micro-Chunk Purge: Drop junk chunks under 0.5 seconds
        merged_turns = [t for t in merged_turns if (t["end"] - t["start"]) >= 0.5]

        # STAGE 3.5: Strict Minimum 15-Second Enforcement
        merged_turns = enforce_minimum_chunk_duration(merged_turns, audio_data, sample_rate, min_dur=15.0, max_dur=30.0)

        # STAGE 4: Contiguous Timeline Partitioning
        from app.services.vcta.contiguous_math import calculate_contiguous_timeline
        logger.info("[CHUNKER] STAGE 4: Contiguous Timeline Partitioning (Zero-Gap Math)")
        contiguous_chunks = calculate_contiguous_timeline(merged_turns, total_duration)
        
        return contiguous_chunks, purged_turns

    return await asyncio.to_thread(_diarize)
