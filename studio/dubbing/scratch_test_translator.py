import asyncio
import logging
import os
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO)

load_dotenv()

from app.services.vcta.translator import batch_translate_text

async def main():
    chunks = [
        {"chunk_id": "1", "kurdish_raw": "سڵاو, چۆنی؟", "speech_duration": 2.0},
        {"chunk_id": "2", "kurdish_raw": "ئەمە تاقیکردنەوەیە", "speech_duration": 2.0},
    ]
    print("Starting translation...")
    result = await batch_translate_text(chunks, batch_size=2)
    print("Translation finished!")
    for c in result:
        print(c.get("chunk_id"), c.get("arabic_text", ""))

if __name__ == "__main__":
    asyncio.run(main())
