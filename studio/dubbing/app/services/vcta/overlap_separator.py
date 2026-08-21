"""
overlap_separator.py — Speech-to-Speech Source Separation for Overlap Sub-Chunks
==================================================================================
Uses SpeechBrain SepFormer (trained on WSJ0-2mix) to separate two simultaneous
voices in a mixed overlap segment.

After separation, matches each stem to the correct speaker using cosine similarity
against the clean master timbre reference pools (ECAPA-TDNN embeddings).
"""

import os
import logging
import tempfile
import numpy as np
import soundfile as sf
import torch

logger = logging.getLogger(__name__)


_SEPFORMER_MODEL = None

def _patch_windows_symlinks():
    """
    Monkey-patches pathlib.Path.symlink_to to fall back to shutil.copy2 on
    Windows when Developer Mode is off (OSError WinError 1314).
    Applied once globally — safe to call multiple times.
    """
    import pathlib
    import shutil as _shutil

    _orig_symlink_to = pathlib.Path.symlink_to

    def _safe_symlink_to(self, target, target_is_directory=False):
        try:
            _orig_symlink_to(self, target, target_is_directory=target_is_directory)
        except OSError as e:
            if getattr(e, "winerror", None) == 1314:
                # Fall back to copying instead of symlinking
                src = pathlib.Path(target)
                if src.is_file():
                    self.parent.mkdir(parents=True, exist_ok=True)
                    _shutil.copy2(str(src), str(self))
                elif src.is_dir():
                    if not self.exists():
                        _shutil.copytree(str(src), str(self))
            else:
                raise

    pathlib.Path.symlink_to = _safe_symlink_to


def get_sepformer():
    """Lazy-load SepFormer model once, reuse across calls."""
    global _SEPFORMER_MODEL
    if _SEPFORMER_MODEL is None:
        from speechbrain.inference.separation import SepformerSeparation

        _patch_windows_symlinks()

        logger.info("[SEPARATOR] Loading SpeechBrain SepFormer (speechbrain/sepformer-whamr)...")
        savedir = os.path.join(os.path.expanduser("~"), ".cache", "speechbrain", "sepformer-whamr")
        _SEPFORMER_MODEL = SepformerSeparation.from_hparams(
            source="speechbrain/sepformer-whamr",
            savedir=savedir,
        )
        logger.info("[SEPARATOR] SepFormer loaded.")
    return _SEPFORMER_MODEL


def _get_embedding(audio: np.ndarray, sr: int) -> np.ndarray:
    """Get ECAPA-TDNN 192-d biometric embedding for an audio clip."""
    from speechbrain.inference.speaker import EncoderClassifier
    import torch

    classifier = EncoderClassifier.from_hparams(
        source="speechbrain/spkrec-ecapa-voxceleb",
        savedir=os.path.join(os.path.expanduser("~"), ".cache", "speechbrain", "spkrec-ecapa"),
        run_opts={"device": "cpu"},
    )

    # Resample to 16kHz if needed
    if sr != 16000:
        import librosa
        audio = librosa.resample(audio, orig_sr=sr, target_sr=16000)

    waveform = torch.from_numpy(audio).float().unsqueeze(0)
    with torch.no_grad():
        embedding = classifier.encode_batch(waveform)
    return embedding.squeeze().cpu().numpy()


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two vectors."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a < 1e-9 or norm_b < 1e-9:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def separate_overlap_segment(
    overlap_audio: np.ndarray,
    sr: int,
    master_pools: dict[str, str],  # {"Speaker_A": "/path/to/master_ref_Speaker_A.wav", ...}
    output_dir: str,
    segment_label: str = "overlap",
) -> dict[str, str]:
    """
    Separates a mixed overlap audio segment into individual speaker stems.

    Args:
        overlap_audio: numpy array of the mixed overlap audio
        sr: sample rate
        master_pools: dict mapping speaker_id -> path to clean master timbre reference wav
        output_dir: directory to write separated stems
        segment_label: label for output filenames

    Returns:
        dict mapping speaker_id -> path to their separated stem wav
    """
    os.makedirs(output_dir, exist_ok=True)

    if len(overlap_audio.shape) > 1:
        overlap_audio = overlap_audio.mean(axis=1)

    # SepFormer requires 8kHz or 16kHz mono input
    # Resample to 8kHz (sepformer-whamr is trained on 8kHz)
    import librosa
    audio_8k = librosa.resample(overlap_audio, orig_sr=sr, target_sr=8000)

    # Write temp file for SepFormer
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name
    sf.write(tmp_path, audio_8k, 8000, subtype="PCM_16")

    # Run SepFormer — use separate_batch() directly to bypass k2 audio_io dependency
    sepformer = get_sepformer()
    logger.info(f"[SEPARATOR] Separating overlap segment '{segment_label}' ({len(audio_8k)/8000:.2f}s)...")

    # SepFormer expects a [batch, time] float tensor at 8kHz
    mix_tensor = torch.from_numpy(audio_8k).float().unsqueeze(0)  # [1, T]
    with torch.no_grad():
        est_sources = sepformer.separate_batch(mix_tensor)  # [batch, time, n_sources]
    # Squeeze batch dim → [time, n_sources]
    est_sources = est_sources.squeeze(0)

    os.unlink(tmp_path)

    n_sources = est_sources.shape[-1]
    logger.info(f"[SEPARATOR] SepFormer produced {n_sources} source stems.")

    # Extract each stem at original SR for embedding comparison
    stems = []
    for i in range(n_sources):
        stem_8k = est_sources[:, i].cpu().numpy()
        # Resample back to original SR
        stem_orig_sr = librosa.resample(stem_8k, orig_sr=8000, target_sr=sr)
        stems.append(stem_orig_sr)

    # Load master reference embeddings
    logger.info("[SEPARATOR] Computing biometric embeddings for speaker matching...")
    ref_embeddings = {}
    for spk_id, ref_path in master_pools.items():
        if not os.path.exists(ref_path):
            continue
        ref_audio, ref_sr = sf.read(ref_path, dtype="float32")
        if len(ref_audio.shape) > 1:
            ref_audio = ref_audio.mean(axis=1)
        ref_embeddings[spk_id] = _get_embedding(ref_audio, ref_sr)
        logger.info(f"[SEPARATOR] Loaded reference embedding for {spk_id}")

    # Compute stem embeddings
    stem_embeddings = []
    for stem in stems:
        emb = _get_embedding(stem, sr)
        stem_embeddings.append(emb)

    # Hungarian-style assignment: match each stem to the closest speaker reference
    # For 2-stem case: try both assignments and take the best total similarity
    assignments = {}  # speaker_id -> stem_index

    if len(ref_embeddings) >= 2 and len(stems) >= 2:
        speaker_ids = list(ref_embeddings.keys())
        
        # Score both possible assignments (stem 0 -> spk[0], stem 1 -> spk[1]) vs (stem 0 -> spk[1], stem 1 -> spk[0])
        score_fwd = sum(
            _cosine_similarity(stem_embeddings[i], ref_embeddings[speaker_ids[i]])
            for i in range(min(len(stems), len(speaker_ids)))
        )
        score_rev = sum(
            _cosine_similarity(stem_embeddings[i], ref_embeddings[speaker_ids[len(speaker_ids)-1-i]])
            for i in range(min(len(stems), len(speaker_ids)))
        )

        if score_fwd >= score_rev:
            for i, spk in enumerate(speaker_ids[:len(stems)]):
                assignments[spk] = i
        else:
            for i, spk in enumerate(reversed(speaker_ids[:len(stems)])):
                assignments[spk] = i

        logger.info(f"[SEPARATOR] Assignment: fwd={score_fwd:.3f} rev={score_rev:.3f} → {'forward' if score_fwd >= score_rev else 'reversed'}")
    else:
        # Greedy assignment: each stem to best unassigned speaker
        used_stems = set()
        for spk_id, ref_emb in ref_embeddings.items():
            best_score = -1.0
            best_stem_idx = 0
            for j, stem_emb in enumerate(stem_embeddings):
                if j in used_stems:
                    continue
                score = _cosine_similarity(stem_emb, ref_emb)
                if score > best_score:
                    best_score = score
                    best_stem_idx = j
            assignments[spk_id] = best_stem_idx
            used_stems.add(best_stem_idx)
            logger.info(f"[SEPARATOR] {spk_id} → stem {best_stem_idx} (similarity={best_score:.3f})")

    # Write output files
    output_paths = {}
    for spk_id, stem_idx in assignments.items():
        out_filename = f"separated_{segment_label}_{spk_id}.wav"
        out_path = os.path.join(output_dir, out_filename)
        sf.write(out_path, stems[stem_idx], sr, subtype="FLOAT")
        output_paths[spk_id] = out_path
        logger.info(f"[SEPARATOR] Saved separated stem: {out_path}")

    return output_paths
