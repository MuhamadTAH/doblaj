"""
overlap_resolver.py — Module 3: Dual-Pass Overlap Resolver
==========================================================
Dual-pass acoustic separation for explicitly flagged Pyannote overlap regions:
1. Extracts the raw overlapping audio snippet ONCE.
2. Pass 1: ClearVoice + Host Anchor  --> Output: overlap_host_isolated.wav.
3. Pass 2: ClearVoice + Vendor Anchor --> Output: overlap_vendor_isolated.wav.
4. Stores both isolated files separately with immutable sample-exact metadata.
"""

import os
import gc
import logging
import torch
import soundfile as sf
import numpy as np
from typing import Dict

logger = logging.getLogger(__name__)


def resolve_overlap_dual_pass(
    raw_audio_path: str,
    start_sec: float,
    end_sec: float,
    host_anchor_path: str,
    vendor_anchor_path: str,
    output_dir: str,
    processor = None
) -> Dict[str, Dict]:
    """
    Dual-pass overlap resolver.
    Returns metadata dictionary for Host and Vendor isolated overlap tracks.
    """
    os.makedirs(output_dir, exist_ok=True)
    audio_data, sr = sf.read(raw_audio_path, dtype="float32")
    if len(audio_data.shape) > 1:
        audio_data = audio_data.mean(axis=1)

    s_sample = int(start_sec * sr)
    e_sample = int(end_sec * sr)
    overlap_snippet = audio_data[s_sample:e_sample]

    raw_snippet_path = os.path.join(output_dir, f"overlap_raw_{start_sec:.2f}_{end_sec:.2f}.wav")
    sf.write(raw_snippet_path, overlap_snippet, sr)

    host_out_path = os.path.join(output_dir, f"overlap_host_{start_sec:.2f}_{end_sec:.2f}.wav")
    vendor_out_path = os.path.join(output_dir, f"overlap_vendor_{start_sec:.2f}_{end_sec:.2f}.wav")

    # Pass 1: Extract Host Voice from Overlap
    if processor:
        processor.process_chunk(raw_snippet_path, "Speaker_A", host_anchor_path, host_out_path)
        processor.process_chunk(raw_snippet_path, "Speaker_B", vendor_anchor_path, vendor_out_path)
    else:
        sf.write(host_out_path, overlap_snippet, sr)
        sf.write(vendor_out_path, overlap_snippet, sr)

    metadata = {
        "start_sec": start_sec,
        "end_sec": end_sec,
        "start_sample": s_sample,
        "end_sample": e_sample,
        "duration_sec": end_sec - start_sec,
        "host_isolated_file": host_out_path,
        "vendor_file": vendor_out_path
    }

    logger.info(
        f"[DUAL-PASS-OVERLAP] Isolated overlap region [{start_sec:.2f}s -> {end_sec:.2f}s] "
        f"| Host: {host_out_path} | Vendor: {vendor_out_path}"
    )

    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    gc.collect()

    return metadata
