"""
acoustic_boundary_matrix.py — Tri-Metric Physical Speaker Transition Matrix
=============================================================================
Combines:
1. Spectral Envelope Delta (MFCC Cosine Distance Derivative - Vocal Tract Shift)
2. Fundamental Frequency Tracking (F0 Discontinuity - Vocal Cord Shift)
3. Deep-Learning Voice Activity (Silero VAD - Neural Phoneme Micro-Pauses)

Finds the exact physical millisecond where vocal anatomy shifts from Speaker 1 to Speaker 2.
"""

import numpy as np
import librosa
import torch
import soundfile as sf
import os

_SILERO_MODEL = None

def get_silero_vad():
    global _SILERO_MODEL
    if _SILERO_MODEL is None:
        try:
            from silero_vad import load_silero_vad
            _SILERO_MODEL = load_silero_vad()
        except Exception:
            _SILERO_MODEL = torch.hub.load(
                repo_or_dir='snakers4/silero-vad',
                model='silero_vad',
                trust_repo=True
            )
    return _SILERO_MODEL


def compute_spectral_delta(y: np.ndarray, sr: int, hop_len: int, win_frames: int = 5) -> np.ndarray:
    """
    Computes the spectral envelope distance (vocal tract shift)
    by comparing MFCC feature vectors before and after each frame.
    """
    # 20 MFCCs captures fine-grained vocal tract resonances (formants)
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=20, hop_length=hop_len) # [n_mfcc, n_frames]
    n_frames = mfcc.shape[1]
    delta = np.zeros(n_frames, dtype=np.float32)

    # Normalize MFCCs across time
    mfcc_norm = (mfcc - np.mean(mfcc, axis=1, keepdims=True)) / (np.std(mfcc, axis=1, keepdims=True) + 1e-6)

    for i in range(win_frames, n_frames - win_frames):
        left_vec = np.mean(mfcc_norm[:, i - win_frames : i], axis=1)
        right_vec = np.mean(mfcc_norm[:, i : i + win_frames], axis=1)

        # Cosine distance = 1 - cosine_similarity
        norm_l = np.linalg.norm(left_vec)
        norm_r = np.linalg.norm(right_vec)
        if norm_l > 1e-6 and norm_r > 1e-6:
            cos_sim = np.dot(left_vec, right_vec) / (norm_l * norm_r)
            delta[i] = float(1.0 - cos_sim)
        else:
            delta[i] = 0.0

    return delta


def compute_f0_discontinuity(y: np.ndarray, sr: int, hop_len: int) -> np.ndarray:
    """
    Computes pitch contour jump (fundamental frequency discontinuity).
    """
    # Fast pyin pitch tracking between 65Hz (deep male) and 500Hz (high scream/female)
    try:
        f0, _, _ = librosa.pyin(
            y,
            fmin=librosa.note_to_hz('C2'),
            fmax=librosa.note_to_hz('C5'),
            sr=sr,
            hop_length=hop_len,
            fill_na=0.0
        )
    except Exception:
        f0 = np.zeros(int(len(y) / hop_len) + 1)

    n_frames = len(f0)
    f0_delta = np.zeros(n_frames, dtype=np.float32)

    for i in range(1, n_frames - 1):
        if f0[i-1] > 0 and f0[i+1] > 0:
            # Relative pitch shift in semitones / ratio
            f0_delta[i] = float(abs(f0[i+1] - f0[i-1]) / (f0[i-1] + 1e-6))
        elif (f0[i-1] > 0 and f0[i+1] == 0) or (f0[i-1] == 0 and f0[i+1] > 0):
            # Voiced <-> Unvoiced transition boundary
            f0_delta[i] = 0.5

    return f0_delta


def compute_silero_vad_prob(y: np.ndarray, sr: int, hop_len: int, target_frames: int) -> np.ndarray:
    """
    Evaluates Silero VAD neural speech probability per frame.
    Returns array of shape [target_frames] where lower value = micro-pause.
    """
    vad_model = get_silero_vad()
    
    # Silero requires 16kHz
    if sr != 16000:
        y_16k = librosa.resample(y, orig_sr=sr, target_sr=16000)
    else:
        y_16k = y

    # Process in chunks of 512 samples (32ms at 16k)
    vad_chunk = 512
    vad_probs = []
    
    tensor_audio = torch.from_numpy(y_16k).float()
    for i in range(0, len(tensor_audio) - vad_chunk, vad_chunk):
        chunk = tensor_audio[i : i + vad_chunk]
        with torch.no_grad():
            prob = vad_model(chunk, 16000).item()
        vad_probs.append(prob)

    if not vad_probs:
        return np.ones(target_frames, dtype=np.float32)

    # Interpolate to match target_frames
    orig_x = np.linspace(0, 1, len(vad_probs))
    target_x = np.linspace(0, 1, target_frames)
    interpolated = np.interp(target_x, orig_x, vad_probs)
    return interpolated


def find_optimal_physical_boundary(
    audio_data: np.ndarray,
    sr: int,
    search_start_sec: float,
    search_end_sec: float,
    w_mfcc: float = 0.45,
    w_f0: float = 0.25,
    w_vad: float = 0.30
) -> float:
    """
    Finds the exact physical speaker boundary by maximizing the tri-metric matrix:
    Score(t) = w_mfcc * norm(ΔMFCC) + w_f0 * norm(ΔF0) + w_vad * (1 - VAD_prob)
    """
    s_sample = max(0, int(search_start_sec * sr))
    e_sample = min(len(audio_data), int(search_end_sec * sr))
    
    if e_sample <= s_sample + int(0.08 * sr):
        return search_start_sec

    sub = audio_data[s_sample:e_sample]
    hop_len = int(0.010 * sr) # 10ms frame resolution
    
    # 1. MFCC Spectral Delta
    mfcc_delta = compute_spectral_delta(sub, sr, hop_len, win_frames=4)
    n_frames = len(mfcc_delta)
    
    # 2. Pitch F0 Discontinuity
    f0_delta = compute_f0_discontinuity(sub, sr, hop_len)
    if len(f0_delta) < n_frames:
        f0_delta = np.pad(f0_delta, (0, n_frames - len(f0_delta)))
    else:
        f0_delta = f0_delta[:n_frames]

    # 3. Silero VAD Micro-Pauses (Inverted: higher score = deeper pause)
    vad_prob = compute_silero_vad_prob(sub, sr, hop_len, target_frames=n_frames)
    pause_score = 1.0 - vad_prob

    # Normalize components to [0, 1]
    def _norm(x):
        mx = np.max(x) if len(x) > 0 else 0
        mn = np.min(x) if len(x) > 0 else 0
        if mx - mn > 1e-6:
            return (x - mn) / (mx - mn)
        return np.zeros_like(x)

    norm_mfcc = _norm(mfcc_delta)
    norm_f0 = _norm(f0_delta)
    norm_pause = _norm(pause_score)

    # Fused Decision Matrix
    score = (w_mfcc * norm_mfcc) + (w_f0 * norm_f0) + (w_vad * norm_pause)

    # Search for peak after the first 30ms and before the last 30ms
    pad_frames = int(0.030 / 0.010) # 3 frames
    if len(score) > 2 * pad_frames:
        valid_score = score[pad_frames : -pad_frames]
        best_frame = pad_frames + int(np.argmax(valid_score))
    else:
        best_frame = int(np.argmax(score))

    times = search_start_sec + librosa.frames_to_time(np.arange(n_frames), sr=sr, hop_length=hop_len)
    optimal_sec = round(float(times[best_frame]), 3)

    return optimal_sec
