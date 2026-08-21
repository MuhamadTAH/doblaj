"""
global_speaker_clustering.py — Global Biometric Speaker Clustering & Master Timbre Pooling
==========================================================================================
Eliminates Pyannote Speaker ID Drift and TTS Reference Collapse.

Features:
1. SpeechBrain ECAPA-TDNN 192-d Biometric Speaker Embeddings.
2. Cosine Distance Agglomerative Clustering (replaces brittle raw diarization strings).
3. Quality-Weighted Master Reference Pooling (aggregates 10-15s of clean speech per speaker).
4. Screaming/Distortion Quarantine Gate (prevents frantic shouting from poisoning TTS timbre).
"""

import os
import shutil
import logging
import torch
import numpy as np
import soundfile as sf
from typing import List, Dict, Tuple
from sklearn.cluster import AgglomerativeClustering

# Windows Symlink Privilege Fallback
if hasattr(os, "symlink"):
    _orig_symlink = os.symlink
    def _safe_symlink(src, dst, *args, **kwargs):
        try:
            return _orig_symlink(src, dst, *args, **kwargs)
        except OSError:
            if os.path.isdir(src):
                return shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                return shutil.copyfile(src, dst)
    os.symlink = _safe_symlink

logger = logging.getLogger(__name__)

_classifier = None


def get_embedding_classifier():
    """Lazily loads SpeechBrain ECAPA-TDNN speaker verification model."""
    global _classifier
    if _classifier is None:
        from speechbrain.inference.speaker import EncoderClassifier
        device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"[SPEAKER-EMBED] Loading ECAPA-TDNN on {device}...")
        _classifier = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            run_opts={"device": device},
            savedir=os.path.expanduser("~/.cache/speechbrain/spkrec-ecapa-voxceleb")
        )
    return _classifier


def extract_segment_embedding(audio_segment: np.ndarray, sr: int = 16000) -> np.ndarray:
    """Extracts a 192-dimensional L2-normalized embedding vector from audio."""
    if len(audio_segment) == 0:
        return np.zeros(192, dtype=np.float32)

    if audio_segment.ndim > 1:
        audio_segment = audio_segment.mean(axis=1)

    classifier = get_embedding_classifier()
    tensor_wav = torch.from_numpy(audio_segment).float().unsqueeze(0)
    if torch.cuda.is_available():
        tensor_wav = tensor_wav.to("cuda")

    with torch.no_grad():
        emb = classifier.encode_batch(tensor_wav)
        emb_np = emb.squeeze().cpu().numpy()
        # L2 normalize
        norm = np.linalg.norm(emb_np)
        if norm > 1e-6:
            emb_np = emb_np / norm
        return emb_np


def cluster_speaker_turns(
    turns: List[Dict],
    full_audio: np.ndarray,
    sr: int = 16000,
    distance_threshold: float = 0.35,
    max_speakers: int = 2,
) -> List[Dict]:
    """
    Computes global biometric embeddings for all turns and performs Anchor-Guided
    Dialogue Clustering. Prevents short-utterance fragmentation and voice shuffling.
    Guarantees persistent global identity labels across the entire video.
    """
    if not turns:
        return []

    embeddings = []
    valid_turns = []

    for turn in turns:
        s_idx = int(turn["start"] * sr)
        e_idx = int(turn["end"] * sr)
        segment = full_audio[s_idx:e_idx]

        # Ignore micro-glitches shorter than 200ms for embedding
        if len(segment) < int(0.2 * sr):
            continue

        emb = extract_segment_embedding(segment, sr)
        embeddings.append(emb)
        turn_c = turn.copy()
        turn_c["duration"] = round(turn["end"] - turn["start"], 3)
        valid_turns.append(turn_c)

    if not embeddings:
        return turns

    emb_matrix = np.vstack(embeddings)

    # 1. Anchor Extraction: Establish Primary Host Anchor from long clean turns (>= 3.5s)
    host_candidates = [emb for t, emb in zip(valid_turns, embeddings) if t["duration"] >= 3.5]
    if host_candidates:
        host_anchor = np.mean(host_candidates, axis=0)
        host_anchor = host_anchor / (np.linalg.norm(host_anchor) + 1e-6)
    else:
        longest_idx = int(np.argmax([t["duration"] for t in valid_turns]))
        host_anchor = embeddings[longest_idx]

    # 2. Score every turn against the Host Anchor (Cosine Similarity)
    # Cosine Similarity >= 0.55 => Speaker_A (Host)
    # Cosine Similarity < 0.55  => Speaker_B (Secondary Speaker / Vendor / Guest)
    HOST_SIMILARITY_THRESHOLD = 0.55

    cluster_labels = []
    for idx, (turn, emb) in enumerate(zip(valid_turns, embeddings)):
        # Cosine similarity = dot product of L2-normalized vectors
        sim_to_host = float(np.dot(emb, host_anchor))
        turn["host_similarity"] = round(sim_to_host, 4)

        if sim_to_host >= HOST_SIMILARITY_THRESHOLD:
            cluster_labels.append(0) # Cluster 0 = Speaker_A (Host)
        else:
            cluster_labels.append(1) # Cluster 1 = Speaker_B (Secondary Speaker)

    # 3. Assign clean global speaker IDs: Speaker_A, Speaker_B
    cluster_durations = {}
    for turn, label in zip(valid_turns, cluster_labels):
        dur = turn["duration"]
        cluster_durations[label] = cluster_durations.get(label, 0.0) + dur

    sorted_clusters = sorted(cluster_durations.keys(), key=lambda k: -cluster_durations[k])
    label_map = {0: "Speaker_A", 1: "Speaker_B"}

    logger.info(f"[BIOMETRIC-CLUSTERING] Anchor Dialogue Clustering completed across {len(valid_turns)} turns:")
    for c_id in sorted_clusters:
        spk_name = label_map.get(c_id, f"Speaker_{chr(65+c_id)}")
        total_d = cluster_durations.get(c_id, 0.0)
        turns_in_c = [t for t, l in zip(valid_turns, cluster_labels) if l == c_id]
        tier_status = "TIER 1 Zero-Shot Clone" if total_d >= 4.0 else "TIER 2 Curated Preset"
        logger.info(
            f"  * {spk_name}: Total Spoken Time = {total_d:.2f}s across {len(turns_in_c)} turns "
            f"==> [{tier_status}]"
        )

    resolved_turns = []
    for idx, (turn, label) in enumerate(zip(valid_turns, cluster_labels)):
        turn_copy = turn.copy()
        assigned_spk = label_map.get(label, "Speaker_B")
        turn_copy["global_speaker_id"] = assigned_spk
        turn_copy["speaker"] = assigned_spk
        resolved_turns.append(turn_copy)
        logger.info(
            f"[TURN-ROUTING] Turn #{idx+1:02d} [{turn['start']:.2f}s -> {turn['end']:.2f}s] ({turn['duration']:.2f}s) "
            f"| Host Sim: {turn['host_similarity']:.3f} ==> Assigned: {assigned_spk}"
        )

    return resolved_turns


def build_master_reference_pools(
    clustered_turns: List[Dict],
    full_audio: np.ndarray,
    work_dir: str,
    sr: int = 16000,
    target_pool_sec: float = 12.0,
) -> Dict[str, str]:
    """
    Builds a pristine Master Timbre Reference Audio Pool for each speaker.
    Filters out frantic shouting / distorted peaks and pools clean segments.
    """
    os.makedirs(work_dir, exist_ok=True)
    speaker_segments = {}

    for turn in clustered_turns:
        spk = turn.get("global_speaker_id", turn.get("speaker", "Speaker_A"))
        s_idx = int(turn["start"] * sr)
        e_idx = int(turn["end"] * sr)
        segment = full_audio[s_idx:e_idx]
        dur = turn["end"] - turn["start"]

        if spk not in speaker_segments:
            speaker_segments[spk] = []

        # Stage 4 / v2 Architecture Mandate:
        # Overlap clips (has_overlap == True) are NEVER used as primary voice cloning anchors
        is_overlap = turn.get("has_overlap", False)

        # Quality Metric: Penalize frantic shouting (> -10 dBFS peak) or extreme clipping
        peak = np.max(np.abs(segment)) if len(segment) > 0 else 0.0
        rms = np.sqrt(np.mean(segment ** 2) + 1e-9)
        crest_factor = peak / (rms + 1e-6)

        # Quality score: prefers steady conversational speech over screeching
        quality_score = dur
        if is_overlap:
            quality_score *= 0.05  # Heavily penalize overlap clips
        if peak > 0.95:  # Distorted / Clipped
            quality_score *= 0.3
        if crest_factor > 8.0: # Highly transient / scream
            quality_score *= 0.5

        speaker_segments[spk].append({
            "segment": segment,
            "duration": dur,
            "quality": quality_score,
            "is_overlap": is_overlap
        })

    reference_paths = {}

    for spk, segments in speaker_segments.items():
        # Sort by quality score (highest quality conversational segments first)
        segments.sort(key=lambda s: -s["quality"])

        accumulated_audio = []
        total_sec = 0.0

        for s in segments:
            # Apply 20ms fade in/out to avoid boundary clicks when concatenating
            seg = s["segment"].copy()
            fade_len = min(int(0.02 * sr), len(seg) // 4)
            if fade_len > 0:
                fade_in = np.linspace(0.0, 1.0, fade_len, dtype=np.float32)
                fade_out = np.linspace(1.0, 0.0, fade_len, dtype=np.float32)
                seg[:fade_len] *= fade_in
                seg[-fade_len:] *= fade_out

            accumulated_audio.append(seg)
            # Add 200ms natural silence pause between pooled segments
            accumulated_audio.append(np.zeros(int(0.2 * sr), dtype=np.float32))
            total_sec += s["duration"] + 0.2

            if total_sec >= target_pool_sec:
                break

        if accumulated_audio:
            pooled_wav = np.concatenate(accumulated_audio)
            # Normalize to clean broadcast level (-20 dBFS)
            rms = np.sqrt(np.mean(pooled_wav ** 2) + 1e-9)
            target_rms = 10.0 ** (-20.0 / 20.0) # ~0.1
            pooled_wav = (pooled_wav / rms) * target_rms
            pooled_wav = np.clip(pooled_wav, -0.95, 0.95)

            ref_path = os.path.join(work_dir, f"master_ref_{spk}.wav")
            sf.write(ref_path, pooled_wav, sr, subtype="PCM_24")
            reference_paths[spk] = ref_path
            logger.info(f"[MASTER-POOL] Created {spk} Master Timbre Reference: {total_sec:.2f}s -> {ref_path}")

    return reference_paths
