import logging
import numpy as np
import soundfile as sf

logger = logging.getLogger(__name__)


def restore_secondary_vocals(
    instrumental_path: str,
    vocals_path: str,
    purged_turns: list[dict],
    output_path: str,
    fade_ms: int = 50
) -> str:
    """
    Restores secondary speakers (e.g., Quran/Singing/secondary background speech) from the vocal stem back 
    into the instrumental stem using float32 numpy arrays and crossfaded masking.
    """
    logger.info(f"[RESTORATION] Injecting {len(purged_turns)} purged turns back to M&E track.")
    
    # 1. Load files natively as float32 to prevent integer overflow clipping
    inst_audio, sr = sf.read(instrumental_path, dtype='float32')
    voc_audio, _ = sf.read(vocals_path, dtype='float32')
    
    # Ensure matching lengths (pad if RoFormer/DeepFilterNet had a tiny rounding mismatch)
    min_len = min(len(inst_audio), len(voc_audio))
    inst_audio = inst_audio[:min_len]
    voc_audio = voc_audio[:min_len]
    
    # 2. Create the digital mask (zeros)
    mask = np.zeros_like(voc_audio)
    fade_samples = int((fade_ms / 1000.0) * sr)
    
    # 3. Fill the mask with crossfades to prevent zero-crossing clicks
    for turn in purged_turns:
        start_sample = int(turn['start'] * sr)
        end_sample = int(turn['end'] * sr)
        
        # Safety bounds
        start_sample = max(0, start_sample)
        end_sample = min(len(mask), end_sample)
        
        if end_sample <= start_sample:
            continue
            
        mask[start_sample:end_sample] = 1.0
        
        # Apply linear fade-in
        if start_sample + fade_samples < end_sample:
            fade_in = np.linspace(0.0, 1.0, fade_samples, dtype='float32')
            
            # If stereo/multichannel, reshape fade to match dimensions
            if mask.ndim > 1:
                fade_in = fade_in[:, None]
                
            mask[start_sample : start_sample + fade_samples] = fade_in
            
        # Apply linear fade-out
        if end_sample - fade_samples > start_sample:
            fade_out = np.linspace(1.0, 0.0, fade_samples, dtype='float32')
            
            if mask.ndim > 1:
                fade_out = fade_out[:, None]
                
            mask[end_sample - fade_samples : end_sample] = fade_out

    # 4. Mathematically merge the masked vocals into the instrumental
    restored_vocals = voc_audio * mask
    final_bg = inst_audio + restored_vocals
    
    # 5. Hard clip safety net (Float32 bounds)
    final_bg = np.clip(final_bg, -1.0, 1.0)
    
    # 6. Export as 32-bit float WAV (maintains dynamic range for final loudnorm stage)
    sf.write(output_path, final_bg, sr, subtype='FLOAT')
    
    logger.info(f"[RESTORATION COMPLETE] Saved restored instrumental to: {output_path}")
    return output_path
