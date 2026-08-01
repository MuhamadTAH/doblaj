import os

# Pird: refuse to silently inject mock transcriptions in prod. See pass-7.
_PROD = os.getenv("PIRD_ENV") == "prod"


async def transcribe_all(chunks: list):
    if _PROD:
        raise RuntimeError(
            "transcriber_mock invoked in prod — Gemini transcription must "
            "succeed or fail explicitly, never fall back to mock data"
        )
    for chunk in chunks:
        chunk["kurdish_raw"] = "Mocked transcription because Gemini failed."
        chunk["speaker"] = "A"
    return chunks
