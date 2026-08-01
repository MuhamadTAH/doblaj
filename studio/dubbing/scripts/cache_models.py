import os
import logging
from audio_separator.separator import Separator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cache_models")

def cache_audio_separator_models():
    logger.info("Caching audio-separator models (BS-RoFormer and HTDemucs_ft)...")
    try:
        # Initializing Separator with download_only logic if possible, 
        # or just loading the model which will force it to download.
        # We set an arbitrary output_dir, it won't actually process anything.
        separator = Separator(output_dir="/tmp", log_level=logging.WARNING)
        
        # This will download the weights if they don't exist
        logger.info("Downloading model_bs_roformer_ep_317_sdr_12.9755.ckpt...")
        separator.load_model(model_filename='model_bs_roformer_ep_317_sdr_12.9755.ckpt')
        
        logger.info("Downloading HTDemucs_ft...")
        from demucs.pretrained import get_model
        # Use CPU for caching since build might not have GPU available
        get_model('htdemucs_ft')
        logger.info("HTDemucs_ft cached successfully.")
        
        logger.info("audio-separator models cached successfully.")
    except Exception as e:
        logger.error(f"Failed to cache audio-separator models: {e}")
        import sys
        sys.exit(1)

def cache_pyannote():
    logger.info("Caching pyannote/speaker-diarization-3.1...")
    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token:
        logger.warning("HF_TOKEN not found in environment! Skipping Pyannote caching.")
        logger.warning("You must pass --build-arg HF_TOKEN=your_token during docker build to cache Pyannote.")
        return
    
    try:
        from huggingface_hub import login
        login(token=hf_token)
        # This forces download to ~/.cache/huggingface
        import torchaudio
        if not hasattr(torchaudio, "set_audio_backend"):
            torchaudio.set_audio_backend = lambda x: None
        from pyannote.audio import Pipeline
        pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1")
        if pipeline:
            logger.info("Pyannote cached successfully.")
        else:
            logger.error("Pyannote pipeline returned None.")
            import sys
            sys.exit(1)
    except Exception as e:
        logger.error(f"Failed to cache pyannote: {e}")
        import sys
        sys.exit(1)

if __name__ == "__main__":
    logger.info("Starting model caching script...")
    cache_audio_separator_models()
    cache_pyannote()
    logger.info("Caching complete!")
