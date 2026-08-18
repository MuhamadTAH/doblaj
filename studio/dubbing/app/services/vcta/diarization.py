import os
import logging
import numpy as np
import librosa

logger = logging.getLogger(__name__)


def filter_legitimate_host_speech(vocal_stem_path: str, raw_speech_turns: list[dict]) -> list[dict]:
    """
    Energy-Legitimacy Gate: Purges false-positive CNN speech blips (breaths, noise) 
    so they don't act as false walls against the padding logic.
    """
    try:
        audio, sr = librosa.load(vocal_stem_path, sr=None, mono=True)
        
        # Calculate RMS energy in dB
        rms = librosa.feature.rms(y=audio, frame_length=2048, hop_length=512)[0]
        dbfs = 20 * np.log10(rms + 1e-8)
        
        # Estimate noise floor (10th percentile of energy)
        noise_floor_db = np.percentile(dbfs, 10)
        legitimacy_threshold = noise_floor_db + 10.0  # Must be 10dB louder than noise
        
        valid_speech = []
        for turn in raw_speech_turns:
            start, end = turn["start"], turn["end"]
            duration = end - start
            
            # Morphological check: linguistically real syllables are > 250ms
            if duration < 0.25:
                logger.debug(f"Dropped fake speech (Too short): {duration:.2f}s")
                continue
                
            # Energy check: peak energy must clear the threshold
            start_frame = librosa.time_to_frames(start, sr=sr, hop_length=512)
            end_frame = librosa.time_to_frames(end, sr=sr, hop_length=512)
            
            start_frame = max(0, min(start_frame, len(dbfs) - 1))
            end_frame = max(0, min(end_frame, len(dbfs)))
            
            if start_frame >= end_frame:
                continue
                
            peak_db = np.max(dbfs[start_frame:end_frame])
            
            if peak_db > legitimacy_threshold:
                valid_speech.append(turn)
            else:
                logger.info(f"[LEGITIMACY GATE] Dropped fake speech wall at {start:.2f}s (Peak: {peak_db:.1f}dB, Threshold: {legitimacy_threshold:.1f}dB)")
                
        return valid_speech
    except Exception as e:
        logger.warning(f"[LEGITIMACY GATE] Error filtering speech: {e}")
        return raw_speech_turns

def _patch_huggingface_hub():
    """Patches huggingface_hub functions to convert legacy use_auth_token kwarg to token."""
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
            
            if hasattr(huggingface_hub, "ModelCard") and hasattr(huggingface_hub.ModelCard, "load"):
                orig_load = huggingface_hub.ModelCard.load
                @classmethod
                def _patched_load(cls, *args, **kwargs):
                    if "use_auth_token" in kwargs:
                        kwargs["token"] = kwargs.pop("use_auth_token")
                    return orig_load.__func__(cls, *args, **kwargs)
                huggingface_hub.ModelCard.load = _patched_load
    except Exception as e:
        logger.warning(f"[DIARIZATION] HF patch warning: {e}")

def execute_global_diarization(vocal_stem_path: str, auth_token: str = None):
    """
    Runs global diarization on the pristine vocal stem.
    Calculates the primary speaker by total duration.
    Routes all other speakers to the purged (restoration) list.
    """
    logger.info("[DIARIZATION] Initializing Pyannote 3.1...")
    _patch_huggingface_hub()

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass

    token = auth_token or os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
    if token == "replace_me":
        token = None

    pipeline = None
    if token:
        try:
            from app.services.vcta.chunker import get_pyannote_pipeline
            pipeline = get_pyannote_pipeline()
        except Exception as e:
            logger.warning(f"[DIARIZATION] get_pyannote_pipeline fallback: {e}")

    if not pipeline:
        import torch
        from pyannote.audio import Pipeline
        
        kwargs = {}
        if token:
            kwargs["use_auth_token"] = token
            
        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            **kwargs
        )
        if torch.cuda.is_available():
            pipeline.to(torch.device("cuda"))

    # Run on the entire continuous vocal file
    diarization = pipeline(vocal_stem_path)
    
    # 1. Tally cumulative duration for each speaker
    speaker_durations = {}
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        duration = turn.end - turn.start
        speaker_durations[speaker] = speaker_durations.get(speaker, 0.0) + duration
        
    if not speaker_durations:
        raise ValueError("Pyannote detected no speakers in the vocal stem.")
        
    # 2. The speaker with the most speaking time is the Primary
    primary_speaker = max(speaker_durations, key=speaker_durations.get)
    logger.info(f"[DIARIZATION] Primary Speaker identified as {primary_speaker} ({speaker_durations[primary_speaker]:.2f}s total)")
    
    # 3. Route turns to translation vs. restoration
    primary_turns = []
    purged_turns = []
    
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        turn_dict = {"start": turn.start, "end": turn.end}
        
        if speaker == primary_speaker:
            primary_turns.append(turn_dict)
        else:
            purged_turns.append(turn_dict)
            
    logger.info(f"[DIARIZATION] Kept {len(primary_turns)} primary turns. Purged {len(purged_turns)} secondary turns for restoration.")
    
    return primary_turns, purged_turns


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
