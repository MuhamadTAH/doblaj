"""Shared constants for the video services.

See PIRD-021 in findings_ledger.json — these were previously duplicated in
ai_transcription.py and gemini_transcription.py.
"""

# Pird: hard cap on audio bytes read into memory for LLM transcription.
# Mirrors Fish Audio's documented 10 MB voice-reference limit with headroom
# for the larger multimodal prompts Gemini accepts.
MAX_AUDIO_BYTES = 25 * 1024 * 1024