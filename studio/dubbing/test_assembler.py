import asyncio
import json
from app.services.vcta.assembler import assemble_final_video

async def main():
    with open('data/jobs/sessions/16/job_details.json', 'r', encoding='utf-8') as f:
        chunks = json.load(f)
    try:
        res = await assemble_final_video(
            chunks, 
            'data/jobs/sessions/16/1-separation/Audio_3_Noise_Only.wav', 
            'data/jobs/sessions/16/1-separation/Video_1_Original_Kurdish_Noise.mp4', 
            'data/jobs/sessions/16', 
            None
        )
        print("Success:", res)
    except Exception as e:
        print("Failed:", e)

asyncio.run(main())
