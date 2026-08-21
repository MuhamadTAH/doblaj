"""
eval_metrics.py — Scientific Metric Evaluation Suite for Speech Separation & ASR
================================================================================
Implements standardized objective metrics to replace subjective "ear-judging":
1. Speaker-Attributed Word Error Rate (sa-WER / cpWER) on Kurdish Unicode text.
2. Scale-Invariant Signal-to-Distortion Ratio (SI-SDR in dB).
3. Scale-Invariant Signal-to-Distortion Ratio improvement (SI-SDRi in dB).
4. Scale-Invariant Signal-to-Noise Ratio (SI-SNR in dB).
"""

import numpy as np
import librosa
from typing import List, Dict, Tuple


def normalize_kurdish_text(text: str) -> str:
    """Normalizes Kurdish Sorani Unicode characters for consistent WER computation."""
    if not text:
        return ""
    text = text.replace("ي", "ی").replace("ك", "ک").replace("ە", "ە").replace("ھ", "هـ")
    # Strip punctuation
    for p in "،؛؟!.()[]{}\"':-":
        text = text.replace(p, " ")
    return " ".join(text.strip().split())


def calculate_wer(reference: str, hypothesis: str) -> float:
    """
    Standard Word Error Rate (WER) using Levenshtein distance on words.
    WER = (Substitutions + Deletions + Insertions) / Total Reference Words
    """
    ref_words = normalize_kurdish_text(reference).split()
    hyp_words = normalize_kurdish_text(hypothesis).split()

    if not ref_words:
        return 0.0 if not hyp_words else 1.0

    # Levenshtein distance matrix
    d = np.zeros((len(ref_words) + 1, len(hyp_words) + 1), dtype=np.uint32)
    for i in range(len(ref_words) + 1):
        d[i, 0] = i
    for j in range(len(hyp_words) + 1):
        d[0, j] = j

    for i in range(1, len(ref_words) + 1):
        for j in range(1, len(hyp_words) + 1):
            if ref_words[i - 1] == hyp_words[j - 1]:
                d[i, j] = d[i - 1, j - 1]
            else:
                d[i, j] = min(
                    d[i - 1, j] + 1,      # deletion
                    d[i, j - 1] + 1,      # insertion
                    d[i - 1, j - 1] + 1   # substitution
                )

    return float(d[len(ref_words), len(hyp_words)] / len(ref_words))


def calculate_speaker_attributed_wer(
    ground_truth: Dict[str, str], # {"Speaker_A": "ref_text", "Speaker_B": "ref_text"}
    predictions: Dict[str, str]   # {"Speaker_A": "hyp_text", "Speaker_B": "hyp_text"}
) -> Dict[str, float]:
    """
    Calculates Speaker-Attributed Word Error Rate (sa-WER) per speaker and aggregate.
    """
    scores = {}
    total_ref_words = 0
    total_errors = 0

    for spk, ref_text in ground_truth.items():
        hyp_text = predictions.get(spk, "")
        spk_wer = calculate_wer(ref_text, hyp_text)
        scores[f"wer_{spk}"] = spk_wer

        ref_len = len(normalize_kurdish_text(ref_text).split())
        total_ref_words += ref_len
        total_errors += int(spk_wer * ref_len)

    scores["sa_wer_macro_avg"] = float(np.mean([scores[k] for k in scores if k.startswith("wer_")]))
    scores["sa_wer_micro_total"] = float(total_errors / total_ref_words) if total_ref_words > 0 else 0.0
    return scores


def calculate_si_sdr(reference: np.ndarray, estimated: np.ndarray) -> float:
    """
    Computes Scale-Invariant Signal-to-Distortion Ratio (SI-SDR) in dB:
    SI-SDR = 10 * log10(||s_target||^2 / ||e_noise||^2)
    where s_target = (<e, s> / ||s||^2) * s
          e_noise = e - s_target
    """
    # Truncate / pad to matching length
    min_len = min(len(reference), len(estimated))
    ref = reference[:min_len].astype(np.float64)
    est = estimated[:min_len].astype(np.float64)

    # Zero-mean normalization
    ref = ref - np.mean(ref)
    est = est - np.mean(est)

    dot = np.dot(est, ref)
    ref_energy = np.dot(ref, ref) + 1e-8

    # Optimal scaling factor alpha
    alpha = dot / ref_energy
    s_target = alpha * ref
    e_noise = est - s_target

    target_energy = np.dot(s_target, s_target) + 1e-8
    noise_energy = np.dot(e_noise, e_noise) + 1e-8

    si_sdr_val = 10.0 * np.log10(target_energy / noise_energy)
    return float(si_sdr_val)


def calculate_si_sdri(reference: np.ndarray, estimated: np.ndarray, mixture: np.ndarray) -> float:
    """
    Calculates SI-SDR Improvement (SI-SDRi) in dB:
    SI-SDRi = SI-SDR(estimated, reference) - SI-SDR(mixture, reference)
    Positive value indicates genuine acoustic separation improvement.
    """
    sdr_est = calculate_si_sdr(reference, estimated)
    sdr_mix = calculate_si_sdr(reference, mixture)
    return float(sdr_est - sdr_mix)
