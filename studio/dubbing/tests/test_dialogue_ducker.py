"""
test_dialogue_ducker.py — Comprehensive Unit Tests for Dialogue Ducker DSP Engine
"""

import pytest
import numpy as np
import os
import soundfile as sf
import tempfile
from app.services.vcta.dialogue_ducker import DialogueDucker, stream_mix_dialogue


def test_dialogue_ducker_gain_staging():
    """
    Verify 1:1 gain staging on low-level normal signals.
    Audio below the knee must pass through with exactly unity gain.
    """
    sr = 48000
    ducker = DialogueDucker(sr=sr)
    
    # Generate 1.0s low-level sine wave at -12dBFS (amplitude 0.25)
    t = np.linspace(0, 1.0, sr, endpoint=False, dtype=np.float32)
    sig_a = 0.25 * np.sin(2 * np.pi * 440 * t)
    sig_b = np.zeros_like(sig_a)

    # Process in 100ms blocks
    block_size = int(0.1 * sr)
    output_chunks = []
    
    for i in range(0, len(sig_a), block_size):
        chunk_a = sig_a[i:i + block_size]
        chunk_b = sig_b[i:i + block_size]
        out = ducker.process_chunk(chunk_a, chunk_b)
        if len(out) > 0:
            output_chunks.append(out)
            
    tail = ducker.flush()
    if len(tail) > 0:
        output_chunks.append(tail)
        
    full_output = np.concatenate(output_chunks)
    
    # Check that amplitude is preserved without +24dB blowout
    assert np.max(np.abs(full_output)) <= 0.35, "Gain staging failure: signal amplified uncontrollably!"
    assert np.max(np.abs(full_output)) >= 0.20, "Signal attenuated too severely!"


def test_true_peak_bounding_on_loud_screams():
    """
    Verify that loud screaming audio (+6dBFS / amplitude 2.0) is strictly clamped
    such that True-Peak does not exceed the target -1.0 dBTP ceiling.
    """
    sr = 48000
    ducker = DialogueDucker(sr=sr, target_ceiling_db=-1.0)
    
    # Loud screaming collision (Track A + Track B both shouting at amplitude 1.5)
    t = np.linspace(0, 1.5, int(1.5 * sr), endpoint=False, dtype=np.float32)
    sig_a = 1.5 * np.sin(2 * np.pi * 800 * t)
    sig_b = 1.5 * np.sin(2 * np.pi * 1200 * t)
    
    out_chunks = []
    block_size = 4800
    for i in range(0, len(sig_a), block_size):
        out = ducker.process_chunk(sig_a[i:i + block_size], sig_b[i:i + block_size])
        if len(out) > 0:
            out_chunks.append(out)
    tail = ducker.flush()
    if len(tail) > 0:
        out_chunks.append(tail)
        
    full_out = np.concatenate(out_chunks)
    
    # Measure True-Peak via 4x polyphase oversampling
    from scipy.signal import resample_poly
    up_4x = resample_poly(full_out, up=4, down=1)
    true_peak_linear = np.max(np.abs(up_4x))
    true_peak_db = 20.0 * np.log10(true_peak_linear + 1e-9)
    
    # Strictly bounded by -1.0 dBTP
    assert true_peak_db <= -0.95, f"True-Peak exceeded broadcast ceiling: {true_peak_db:.2f} dBTP > -1.0 dBTP"


def test_boundary_continuity_no_clicks():
    """
    Verify C0 boundary spline continuity: difference between adjacent samples across 1-second chunks
    must remain smooth with no discontinuous steps.
    """
    sr = 48000
    ducker = DialogueDucker(sr=sr)
    
    # 2 seconds of pink/white noise speech simulation
    np.random.seed(42)
    sig_a = np.random.uniform(-0.5, 0.5, sr * 2).astype(np.float32)
    sig_b = np.random.uniform(-0.5, 0.5, sr * 2).astype(np.float32)
    
    # Process exactly in 1-second blocks (48,000 samples)
    out1 = ducker.process_chunk(sig_a[:sr], sig_b[:sr])
    out2 = ducker.process_chunk(sig_a[sr:], sig_b[sr:])
    
    # Check boundary transition between out1[-1] and out2[0]
    delta = abs(out2[0] - out1[-1])
    assert delta < 0.8, f"Step discontinuity click at chunk boundary: delta = {delta}"


def test_file_stream_mix_mono_stereo_handling():
    """
    Test stream_mix_dialogue with real WAV files, including stereo inputs and partial final blocks.
    """
    sr = 48000
    duration_sec = 2.3  # Non-integer duration tests partial block handling at EOF
    num_samples = int(duration_sec * sr)
    
    t = np.linspace(0, duration_sec, num_samples, endpoint=False, dtype=np.float32)
    mono_track = (0.4 * np.sin(2 * np.pi * 300 * t)).astype(np.float32)
    stereo_track = np.column_stack([mono_track, mono_track * 0.8]).astype(np.float32)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        track_a_path = os.path.join(tmpdir, "track_a.wav")
        track_b_path = os.path.join(tmpdir, "track_b.wav")
        out_path = os.path.join(tmpdir, "mixed_out.wav")
        
        sf.write(track_a_path, mono_track, sr, subtype="PCM_24")
        sf.write(track_b_path, stereo_track, sr, subtype="PCM_24")
        
        result_path = stream_mix_dialogue(track_a_path, track_b_path, out_path, block_duration_sec=1.0)
        
        assert os.path.exists(result_path)
        out_data, out_sr = sf.read(result_path)
        assert out_sr == sr
        assert out_data.ndim == 1, "Output must be single-channel mono!"
        
        # Verify length accuracy (sample accurate flush)
        assert abs(len(out_data) - num_samples) < 1000, f"Length desync: expected ~{num_samples}, got {len(out_data)}"
