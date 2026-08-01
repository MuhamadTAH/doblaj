import numpy as np
import scipy.io.wavfile as wavfile
import logging

logger = logging.getLogger(__name__)

def restore_background_vocals(
    vocals_wav_path: str,
    instrumental_wav_path: str,
    output_bg_wav_path: str,
    output_vocals_wav_path: str,
    purged_turns: list[dict]
) -> bool:
    """
    V2.4 Architecture Addon: Background Vocal Restoration
    Loads vocals.wav and instrumental.wav natively into numpy arrays.
    Isolates the audio corresponding to `purged_turns` from vocals.wav,
    mixes it back into instrumental.wav, and exports with clipping protection.
    
    purged_turns is a list of dicts: [{"start": 10.5, "end": 12.0, "speaker": "SPEAKER_01"}]
    """
    if not purged_turns:
        logger.info("[RESTORATION] No purged turns to restore. Using instrumental track as is.")
        import shutil
        # Pird: was NameError — output_wav_path is not a parameter.
        shutil.copy(instrumental_wav_path, output_bg_wav_path)
        return True
        
    try:
        logger.info("[RESTORATION] Loading audio stems into RAM for Numpy mathematical mix...")
        v_rate, v_data = wavfile.read(vocals_wav_path)
        i_rate, i_data = wavfile.read(instrumental_wav_path)
        
        if v_rate != i_rate:
            raise ValueError(f"Sample rate mismatch: vocals ({v_rate}) vs instrumental ({i_rate})")
            
        # Ensure arrays are exactly the same length
        min_len = min(len(v_data), len(i_data))
        v_data = v_data[:min_len]
        i_data = i_data[:min_len]
        
        # Convert to float32 to prevent integer overflow during addition
        v_float = v_data.astype(np.float32)
        i_float = i_data.astype(np.float32)
        
        # Create a boolean mask of the same shape as the audio arrays
        mask = np.zeros(min_len, dtype=bool)
        
        restored_duration = 0.0
        
        for turn in purged_turns:
            start_sample = int(turn["start"] * v_rate)
            end_sample = int(turn["end"] * v_rate)
            
            # Clamp bounds
            start_sample = max(0, start_sample)
            end_sample = min(min_len, end_sample)
            
            mask[start_sample:end_sample] = True
            restored_duration += (turn["end"] - turn["start"])
            
        logger.info(f"[RESTORATION] Injecting {restored_duration:.2f} seconds of purged vocals back into the background track...")
        
        # Apply mask: Zero out the vocals everywhere except during the purged turns
        # If stereo (2D array), we need to expand the mask to 2D
        if len(v_float.shape) == 2:
            mask = mask[:, np.newaxis]
            
        v_float_masked = np.where(mask, v_float, 0.0)
        
        # Array Addition
        mixed_float = i_float + v_float_masked
        
        # Peak Normalization / Limiter implementation
        # Find absolute max peak to prevent > 0dBFS clipping
        peak = np.max(np.abs(mixed_float))
        
        # Audio physics safeguard for float32 (max 1.0)
        FLOAT_MAX = 1.0
        
        if peak > FLOAT_MAX:
            logger.warning(f"[RESTORATION] Peak overload detected ({peak} > {FLOAT_MAX}). Applying perfect normalization (-0.1dB) to prevent digital clipping.")
            # Normalize to exactly -0.1 dBFS to leave absolute headroom
            target_peak = FLOAT_MAX * 0.9885  # ~ -0.1 dBFS
            scale_factor = target_peak / peak
            mixed_float = mixed_float * scale_factor
            
        logger.info(f"[RESTORATION] Exporting fully restored 44.1kHz instrumental background...")
        wavfile.write(output_bg_wav_path, v_rate, mixed_float)
        
        # Save the vocals track with the purged turns muted
        v_float_muted = np.where(~mask, v_float, 0.0)
        logger.info(f"[RESTORATION] Exporting muted vocals track (gaps silenced)...")
        wavfile.write(output_vocals_wav_path, v_rate, v_float_muted)
        
        return True
        
    except Exception as e:
        logger.error(f"[RESTORATION] Numpy restoration failed: {e}")
        return False
