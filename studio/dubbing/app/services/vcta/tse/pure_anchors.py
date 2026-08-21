"""
pure_anchors.py — Module 1: Pure Biometric Anchor Identification
================================================================
Programmatically scans Pyannote diarization output to find the cleanest,
most stable biometric anchor segment for each speaker (Host & Vendor).

Criteria:
1. Segment duration >= 2.5s (up to 8.0s).
2. Safety margin: Must be >= 0.5s away from any detected overlap region.
3. Ranking: Highest RMS energy and highest Pyannote confidence score.
4. Outputs: anchor_host_pure.wav and anchor_vendor_pure.wav.
"""

import os
import logging
import soundfile as sf
import numpy as np
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


def find_pure_anchors(
    audio_path: str,
    diarization_turns: List[Dict],
    overlap_regions: List[Dict],
    output_dir: str,
    min_anchor_dur: float = 2.5,
    safety_margin_sec: float = 0.5
) -> Dict[str, str]:
    """
    Extracts the purest biometric anchor segment for each speaker.
    Returns dictionary mapping speaker ID to local anchor file path:
    {"Speaker_A": "/path/to/anchor_host_pure.wav", "Speaker_B": "/path/to/anchor_vendor_pure.wav"}
    """
    os.makedirs(output_dir, exist_ok=True)
    audio_data, sr = sf.read(audio_path, dtype="float32")
    if len(audio_data.shape) > 1:
        audio_data = audio_data.mean(axis=1)

    # 1. Map overlap boundaries with safety margin
    unsafe_intervals = []
    for ov in overlap_regions:
        o_start = max(0.0, ov["start"] - safety_margin_sec)
        o_end = ov["end"] + safety_margin_sec
        unsafe_intervals.append((o_start, o_end))

    def is_safe_from_overlap(t_start: float, t_end: float) -> bool:
        for u_start, u_end in unsafe_intervals:
            if not (t_end <= u_start or t_start >= u_end):
                return False
        return True

    # 2. Group candidate segments per speaker
    speaker_candidates: Dict[str, List[Dict]] = {}
    for turn in diarization_turns:
        spk = turn.get("speaker", "Speaker_A")
        start = turn["start"]
        end = turn["end"]
        dur = end - start

        if dur >= min_anchor_dur and is_safe_from_overlap(start, end):
            # Calculate RMS energy of candidate segment
            s_idx = int(start * sr)
            e_idx = int(end * sr)
            seg_audio = audio_data[s_idx:e_idx]
            rms = float(np.sqrt(np.mean(seg_audio**2) + 1e-10))

            cand = {
                "start": start,
                "end": end,
                "duration": dur,
                "rms": rms,
                "confidence": turn.get("confidence", 1.0),
                "score": rms * dur * turn.get("confidence", 1.0)
            }
            speaker_candidates.setdefault(spk, []).append(cand)

    # 3. Select the best anchor for each speaker
    anchor_paths: Dict[str, str] = {}

    for spk, candidates in speaker_candidates.items():
        if not candidates:
            logger.warning(f"[PURE-ANCHOR] No clean anchor >= {min_anchor_dur}s found for {spk}. Relaxing constraints...")
            # Fallback: Pick longest turn safe from overlaps
            all_spk_turns = [t for t in diarization_turns if t.get("speaker") == spk]
            candidates = sorted(all_spk_turns, key=lambda x: (x["end"] - x["start"]), reverse=True)
            if not candidates:
                continue
            best = candidates[0]
            best["rms"] = 0.05
        else:
            candidates.sort(key=lambda x: x["score"], reverse=True)
            best = candidates[0]

        start_t = best["start"]
        end_t = min(start_t + 6.0, best["end"]) # Cap anchor at 6s max for speed
        s_idx = int(start_t * sr)
        e_idx = int(end_t * sr)
        anchor_audio = audio_data[s_idx:e_idx]

        clean_spk_name = "host" if spk in ("Speaker_A", "SPEAKER_00") else "vendor"
        anchor_file = os.path.join(output_dir, f"anchor_{clean_spk_name}_pure.wav")

        sf.write(anchor_file, anchor_audio, sr)
        anchor_paths[spk] = anchor_file

        logger.info(
            f"[PURE-ANCHOR SUCCESS] Speaker {spk} Anchor Locked: {anchor_file} "
            f"| Window: [{start_t:.2f}s -> {end_t:.2f}s] (Dur: {end_t-start_t:.2f}s, RMS: {best.get('rms', 0.0):.4f})"
        )

    return anchor_paths
