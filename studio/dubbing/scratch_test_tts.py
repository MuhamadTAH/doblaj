import asyncio
import os
from dotenv import load_dotenv
from app.services.vcta.tts_engine import generate_tts

load_dotenv()

async def main():
    text = "مرحبا كيف حالك"
    ref_audio = "data/jobs/sessions/4/2-chunks/chunk_1_audio.wav"
    output_wav = "scratch_out_tts.wav"
    
    if not os.path.exists(ref_audio):
        print(f"Reference audio not found: {ref_audio}")
        return

    success, err = await generate_tts(text, ref_audio, output_wav)
    print(f"Success: {success}, Error: {err}")

if __name__ == "__main__":
    asyncio.run(main())
