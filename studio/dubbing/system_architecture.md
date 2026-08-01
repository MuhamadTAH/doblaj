# Pird Studio: Dubbing Pipeline Architecture

This document contains a highly detailed, line-by-line breakdown of the core engines powering the automated video dubbing pipeline.

---

## 1. `manual_video.py` (The Traffic Controller)
This file does **not** contain the actual physics or processing code itself. It acts as the **Traffic Controller** (or the "Router").

Its only job is to listen for clicks on the Translate Dashboard, and then **delegate** the heavy lifting to the specialized engine files. 

For example, when you click the "Translate" button on the dashboard:
1. The dashboard sends an HTTP request to `manual_video.py`.
2. `manual_video.py` says, *"Okay, I need to translate these chunks!"*
3. It `imports` the `translator.py` file and says, *"Hey translator, here is the text, go do your magic!"*
4. `translator.py` does all the hard work (talking to OpenRouter, waiting for the AI response).
5. `translator.py` hands the translated text back to `manual_video.py`.
6. `manual_video.py` saves the result to the database and tells the dashboard, *"Done!"*

**Why do it this way?**
If we put all the code into one giant file, it would be thousands of lines long and impossible to debug. By keeping the logic split into dedicated files (`app/services/vcta/`), we get massive benefits:
* **Safety:** If the translation API crashes, it won't take down the stem separator or the chunker.
* **Upgrades:** If we want to replace `ffmpeg` rendering with a different tool later, we only have to edit `assembler.py` and `manual_video.py` won't even know the difference.
* **Speed:** The traffic controller (`manual_video.py`) can tell the background `worker.py` to run 5 different chunks through `tts_engine.py` all at the exact same time!

---

## 2. `isolation.py` (Stem Separation Engine)
This file is the absolute powerhouse of the audio pipeline—its job is to take raw video audio and perfectly extract the Kurdish vocals without destroying the background music. It does this through a highly advanced "VCTA Vocal Isolation v3.0" pipeline involving dual AI models, frequency-domain math, and dynamic padding.

* **Stage 0: Input Validation.** Checks if the file is a valid audio format. It forces the audio into exactly `44100 Hz` sample rate. The AI models expect this exact rate; if it isn't `44100`, it mathematically resamples it.
* **Stage 1: Silence Mapping.** It squashes the stereo audio to mono and calculates the Root Mean Square (RMS) volume level. If the volume drops below `-55.0 dB`, it flags that exact millisecond as "True Silence" in a massive boolean array.
* **Stage 2a: BS-RoFormer.** Runs the first AI model: **BS-RoFormer**. RoFormer is incredible at preserving the "warmth" and high frequencies of a human voice. It loads `model_bs_roformer_ep_317` and isolates the vocals.
* **Stage 2b: HTDemucs_ft.** Runs the second AI model: **HTDemucs Fine-Tuned**. Demucs is a "surgical" model. It passes the raw audio into Demucs using `shifts=4` and `overlap=0.75` (75%) to eliminate glitches.
* **Stage 3: Phase Alignment.** Because RoFormer and Demucs process math differently, their outputs are usually out of sync. It slides the two audio waves across each other (`correlate`) to find the exact point where their peaks perfectly align, then shifts Demucs to lock in sync.
* **Stage 4: Frequency-Domain Ensemble.** It converts both synchronized vocal tracks into the Frequency Domain (a 2D spectrogram). **The Hard Spectral Mask:** It compares the models. If Demucs has less than 10% of the energy of RoFormer in a specific frequency bin, it assumes that frequency is background noise and forces it to absolute zero. Otherwise, it lets RoFormer's warmth shine through.
* **Stage 5: Silence Restoration.** Any millisecond that was mapped as "True Silence" in Stage 1 is forcefully set to `0.0` (dead silence) in the new vocal track. This instantly deletes any AI hallucinations.
* **Stage 6: Quality Gate.** It tests the file. If the audio is 80% dead silence, or Crest Factor is `< 8.0 dB` (transients destroyed), or Spectral Flatness is `< 0.002` (music bleed), it triggers a **FAIL**.
* **Stage 7: Vocal Enhancement.** Runs the Resemble AI enhancer using `nfe=32` to make the voice sound like it was recorded in a professional studio.
* **Stage 8: True Peak Normalization.** Mathematically oversamples the audio by 4X to find the "True Inter-Sample Peak" and adjusts volumes to `-3.0 dB` (Pyannote), `-1.0 dB` (Fish Audio), and `-6.0 dB` (Instrumental).
* **Stage 9: The Orchestrator.** Manages the entire flow, including the **Digital Zero Trap Fix** (reflectively padding 2.0s to the front so AI models don't crash at the 0.0s mark) and strict VRAM garbage collection.

---

## 3. `chunker.py` (Acoustic Diarization)
This file is responsible for **Acoustic Diarization and Contiguous Chunking**. Its job is to listen to the isolated vocals, figure out exactly *when* someone is speaking, and *who* is speaking.

* **Pyannote Initialization.** Boots up the **Pyannote 3.1** AI. It injects a massive custom tweak: **The VAD Override.** By default, Pyannote is bad at handling rapid conversations. We forcefully inject `min_duration_off = 0.3s` and `min_duration_on = 0.1s`.
* **OOM Guard: Silence Splitting.** If a video is longer than 30 minutes, it looks for a block where nobody breathes or speaks for more than 500ms. It slices the massive file in half safely without cutting a word in half to prevent GPU OOM crashes.
* **The Diarization Engine.** Loads audio natively as `float32`. Feeds the tensor into Pyannote, extracts raw turn data, and strictly wipes the GPU cache to prevent memory leaks.
* **Timeline Merging.** The raw AI output is chaotic. The **Strict Adjacency Loop** continuously sweeps over the timeline. If Chunk A and Chunk B are the same speaker, and the silent gap between them is less than 0.5s, it strictly merges them into one chunk.
* **Contiguous Partitioning.** It hands the merged chunks to `contiguous_math.py` to stretch their boundaries so there are absolutely no gaps in the final timeline.

---

## 4. `contiguous_math.py` (Zero-Gap Math)
This file solves the biggest timing bug in any video dubbing system: **Timeline Drift**. It mathematically expands speech blocks forward and backward so that they touch each other perfectly, leaving **zero gaps** in the timeline.

* **Calculating the New Start Time.** It calculates how much silence exists before the chunk. **The Silence Bisection:** If there is a clean gap (e.g., 2.0s), it perfectly splits the silence in half, giving 1.0s to the previous chunk and 1.0s to the current chunk. If the gap is negative (overlapping speech), it hits the **Collision Safeguard** and doesn't stretch backward.
* **Calculating the New End Time.** Does the exact same bisection for the silence *after* the chunk.
* **Mapping the New Timeline.** Overwrites the primary timestamps (`start_time`, `end_time`, `duration`) with the massive new contiguous timestamps. `Chunk 1` and `Chunk 2` now share the exact same split-second boundary!

---

## 5. `translator.py` (The Transcreation Engine)
This file mathematically enforces that the translated Arabic text will physically fit inside the video's exact time slot by forcing the AI to invent dialect-accurate "filler words".

* **The Master Prompt.** Instructs the AI to act as an Iraqi translator. Enforces **Granular Padding** (adding fillers like 'طبعاً', 'أصلاً') if the output is too short. Enforces **Hook Preservation** (forbidding filler at the beginning of the sentence).
* **The Prediction Limit (WPS Bracket).** Takes the video duration (e.g., 5.0s), multiplies by target WPS (2.0), and locks the AI into a strict box (e.g., `min_words: 9, max_words: 11`).
* **The Micro-Chunk Protocol.** If a chunk is `< 0.8s`, it overrides the Master Prompt and tells the AI: *"Translate this to EXACTLY ONE Arabic word."*
* **Context Awareness.** Injects the previously translated sentence into the prompt so the AI can flow the grammar perfectly into the new sentence.
* **Execution.** Uses `google/gemini-3.1-pro-preview` via OpenRouter with `temperature: 0.4` to keep the AI highly deterministic. 
* **Batch Processing.** Fires all translation tasks simultaneously in parallel using `asyncio.gather`.

---

## 6. `voice_router.py` (Cloning Safety Net)
This file scans the video, safely extracts the cleanest possible voice sample for each speaker, and routes those samples to the TTS engine.

* **The Quarantine Filter.** Groups all chunks by speaker. Instantly discards any chunk flagged as a "collision" (overlapping voices). Sorts the pristine chunks from longest to shortest.
* **Micro-VAD Guided Slicing.** Takes the best 5.0s pristine chunk and loads it into a tiny AI model called `silero-vad`. It finds the exact milliseconds where the person is physically talking inside that chunk. It skips the very first block (to avoid boundary bleed) and extracts exactly 5.0s of pure, unbroken speech.
* **The State Machine.** When rendering, it decides what voice to use:
  - **State B (Library Voice):** Uses a pre-selected Fish Audio library voice.
  - **State A (Custom Clone):** Uses a user-uploaded `global_voice_ref.wav`.
  - **State C (Auto):** Uses the pristine `speaker_ref_A.wav` it extracted earlier.
  - **Fallback:** If all else fails, it clones the voice directly from the current Kurdish audio chunk.

---

## 7. `tts_engine.py` (Voice Generation)
This file sends the Arabic text and the Pristine Reference Voice to the Fish Audio API.

* **Reference Trimming.** If the reference audio is padded with silence, it uses FFmpeg to chop it down to only contain the exact `speech_duration`.
* **The Payload Packer.** Fish Audio requires binary data packed using `msgpack`. If cloning a voice, it physically opens the reference `.wav` file, reads it as raw bytes (`rb`), and attaches the raw audio binary directly to the payload alongside the Arabic text.
* **Retry Backoff System.** If the API fails with `429` (Rate Limit) or `502`, it automatically waits `[1, 2, 4]` seconds and tries again up to 4 times before failing.
* **Async Execution.** Downloads the resulting Arabic audio binary and saves it to `output_wav`.

---

## 8. `assembler.py` (Final Video Muxing)
This file stitches the 50+ Arabic audio chunks perfectly back into the original video timeline, ensuring flawless lip-sync.

* **The Silent Master Track.** Calculates the absolute duration of the original video and commands FFmpeg to generate an invisible, perfectly silent audio track of the exact same length.
* **The Absolute Anchor Filtergraph.** This is the complex FFmpeg math. It loops through all 50 chunks and creates a delay string (e.g., `[1:a]adelay=4500|4500[d1]`). This overlays all 50 chunks onto the silent master track at their exact millisecond timestamps simultaneously.
* **The Volume Fix.** Mixes all 50 tracks together using the `amix` filter. It explicitly sets `normalize=0` to prevent FFmpeg from dividing the master volume by 50, which would make the dialogue impossible to hear.
* **The Cinematic Mix.** Loads the new Arabic voice track and the background music. Applies a volume filter (`[0:a]volume=1.0[voice];[1:a]volume=0.8[bg]`) to dip the music to 80% so the voices punch through clearly.
* **Final Video Muxing.** Pairs the new audio with the original MP4. Uses `-c:v copy` to mathematically copy the video pixels without re-rendering them, turning a 2-hour render into a 3-second render.

---

## 9. `gemini_transcription.py` (Mega-Payload Batching)
This file transcribes Kurdish Sorani audio to text using Gemini 3.1 Pro Preview.

* **Base64 Compression.** Because sending raw `.wav` files is slow and expensive, it instantly converts the `.wav` chunks into tiny `64k` `.mp3` files, then encodes them into `base64` text strings.
* **The Batching Engine.** Instead of hitting the API 50 times, it groups chunks into `BATCH_SIZE = 5`.
* **The Mega-Payload Loop.** It sends an array of alternating Text and Audio blocks. It passes the previous translated sentence to maintain grammatical flow. It appends the 5 base64 audio strings.
* **Strict JSON Enforcement.** It dynamically builds a JSON instruction string (e.g., `{"chunk_1": "text", "chunk_2": "text"}`) to force the AI to map its answers perfectly.
* **JSON Surgery.** Automatically strips out markdown formatting (` ```json `) and fixes broken JSON brackets if the AI gets cut off.

---

## 10. `gemini_diarize.py` (Collision Engine)
This file handles Pyannote failures. If two people shout at the exact same time (Collision Chunk), it asks Gemini to figure out the cutover.

* **The Multimodal Payload Trick.** OpenRouter's API struggles with native audio uploads for Gemini. The code uses a brilliant hack: it disguises the base64 audio data as an image URL using a data URI format (`data:audio/mp3;base64,...`). Gemini's multimodal engine realizes it's audio and listens to it perfectly.
* **The Collision Prompt.** Explicitly tells the AI: *"Two people are speaking Kurdish Sorani... Find the exact millisecond where the first speaker stops speaking and the second speaker begins."*
* **JSON Output.** Forces the AI to return exactly three things: the Arabic translation of Speaker 1, the Arabic translation of Speaker 2, and the exact `cut_time_seconds` where the voice changes.
