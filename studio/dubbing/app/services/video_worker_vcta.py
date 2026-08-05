import os
import json
import logging
import asyncio
import uuid
import shutil
import zipfile
from pathlib import Path
import time
import subprocess

from app.core import db as database
from app.core.db import _get_service_role_client
from app.services.video.transcriber import extract_audio
from app.services.vcta import chunker
from app.services.tokenizer import count_words, count_syllables_approx

logger = logging.getLogger(__name__)

# --- PRICING CONSTANTS (Updated: Google Vertex Gemini & Fish Audio S2 Pro) ---
PRICING_GEMINI_INPUT_PER_1M = 2.00
PRICING_GEMINI_OUTPUT_PER_1M = 12.00
PRICING_FISH_AUDIO_PER_1K_BYTES = 0.015
PRICING_GPU_PER_SECOND = 0.0003
PRICING_CPU_PER_SECOND = 0.00005


async def process_video_gpu_phase(job_id: str, input_path: str, workspace_id: str = "", category: str = None, entity: str = None):
    store_id = 0
    job_start_time = time.time()
    total_cost_usd = 0.0
    
    await database.update_job_status(_get_service_role_client(), workspace_id=workspace_id, job_id=job_id, status="separating", progress=5)
    
    jobs_base = Path("data/jobs/sessions")
    jobs_base.mkdir(parents=True, exist_ok=True)
    
    existing_folders = []
    for d in jobs_base.iterdir():
        if d.is_dir() and d.name.isdigit():
            existing_folders.append(int(d.name))
    next_id = max(existing_folders) + 1 if existing_folders else 1
    
    work_dir = jobs_base / str(next_id)
    work_dir.mkdir(parents=True, exist_ok=True)
    
    dir_sep = work_dir / "1-separation"
    dir_chunks = work_dir / "2-chunks"
    dir_transcription = work_dir / "3-transcription"
    dir_translation = work_dir / "4-translation"
    dir_side = work_dir / "5-side_by_side"
    dir_arabic = work_dir / "6-arabic_audio_chunks"
    dir_full_video = work_dir / "7-full_arabic_video_no_noise"
    dir_final = work_dir / "8-final_dubbed_video"
    
    for d in [dir_sep, dir_chunks, dir_transcription, dir_translation, dir_side, dir_arabic, dir_full_video, dir_final]:
        d.mkdir(parents=True, exist_ok=True)
    
    try:
        # Step 0: Global Pre-Stretch (0.95x)
        video_path = dir_sep / "Video_1_Original_Kurdish_Noise.mp4"
        if os.path.exists(input_path) and str(input_path) != str(video_path):
            logger.info(f"[JOB {job_id}] Applying Phase 0: Global Pre-Stretch to 0.95x speed...")
            try:
                cmd = [
                    "ffmpeg", "-y", "-i", str(input_path),
                    "-filter_complex", "[0:v]setpts=1.0526*PTS[v];[0:a]atempo=0.95[a]",
                    "-map", "[v]", "-map", "[a]",
                    "-c:v", "libx264", "-crf", "18", "-preset", "fast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-ar", "44100", "-b:a", "192k",
                    str(video_path)
                ]
                await asyncio.to_thread(
                    subprocess.run, cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True
                )
            except Exception as e:
                logger.error(f"[JOB {job_id}] Phase 0 Pre-Stretch failed: {e}. Falling back to normal copy.")
                shutil.copy(input_path, video_path)
        elif not os.path.exists(input_path):
            raise Exception("We couldn't locate your video file. Please try uploading it again.")
            
        await database.update_job_status(_get_service_role_client(), workspace_id=workspace_id, job_id=job_id, status="separating", progress=10)

        # Step 1: Extract Audio
        logger.info(f"[JOB {job_id}] Step 1: Extracting Audio")
        audio_raw = dir_sep / "Audio_1_Original_Kurdish_Noise.wav"
        success, _ = await extract_audio(str(video_path), str(audio_raw))
        if not success:
            raise Exception("We couldn't read the audio track. Ensure your video file isn't corrupted and try again.")
            
        await database.update_job_status(_get_service_role_client(), workspace_id=workspace_id, job_id=job_id, status="separating", progress=15)

        # Stage 1: The Analysis Sidecar
        logger.info(f"[JOB {job_id}] Stage 1: VCTA Vocal Isolation Pipeline v3.0")
        stage1_start = time.time()
        from app.services.vcta import isolation
        iso_results = await asyncio.to_thread(isolation.run_vcta_pipeline, str(audio_raw), str(dir_sep))
        stage1_dur = (time.time() - stage1_start) * 1000
        stage1_cost = (stage1_dur / 1000) * PRICING_GPU_PER_SECOND
        total_cost_usd += stage1_cost
        await database.create_step_telemetry(
            _get_service_role_client(),
            workspace_id=workspace_id,
            job_id=job_id,
            chunk_index=-1,
            step_name="Vocal Isolation (Demucs)",
            duration_ms=stage1_dur,
            status_code=200,
            compute_provider="runpod_serverless_gpu",
            usage_units=stage1_dur/1000,
            cost_usd=stage1_cost
        )
        
        os.rename(iso_results['paths']['fish_audio'], dir_sep / "Audio_2_Vocal_Only_Kurdish.wav")
        os.rename(iso_results['paths']['instrumental'], dir_sep / "Audio_3_Noise_Only.wav")
        
        pyannote_wav = iso_results['paths']['pyannote']
        fish_wav = str(dir_sep / "Audio_2_Vocal_Only_Kurdish.wav")
        bg_wav = str(dir_sep / "Audio_3_Noise_Only.wav")
        
        logger.info(f"[JOB {job_id}] Stage 1.5: Generating Separated Video Files")
        video_vocal = dir_sep / "Video_2_Vocal_Only_Kurdish.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-i", str(video_path), "-i", fish_wav,
            "-c:v", "copy", "-c:a", "aac", "-map", "0:v:0", "-map", "1:a:0",
            str(video_vocal)
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        video_noise = dir_sep / "Video_3_Noise_Only.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-i", str(video_path), "-i", bg_wav,
            "-c:v", "copy", "-c:a", "aac", "-map", "0:v:0", "-map", "1:a:0",
            str(video_noise)
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        await database.update_job_status(_get_service_role_client(), workspace_id=workspace_id, job_id=job_id, status="separating", progress=30)

        # Stage 2: Acoustic Diarization
        logger.info(f"[JOB {job_id}] Stage 2: Acoustic Diarization (Pyannote)")
        stage2_start = time.time()
        pyannote_turns, purged_turns = await chunker.run_diarization(pyannote_wav)
        stage2_dur = (time.time() - stage2_start) * 1000
        stage2_cost = (stage2_dur / 1000) * PRICING_GPU_PER_SECOND
        total_cost_usd += stage2_cost
        await database.create_step_telemetry(
            _get_service_role_client(),
            workspace_id=workspace_id,
            job_id=job_id,
            chunk_index=-1,
            step_name="Acoustic Diarization (Pyannote)",
            duration_ms=stage2_dur,
            status_code=200,
            compute_provider="runpod_serverless_gpu",
            usage_units=stage2_dur/1000,
            cost_usd=stage2_cost
        )
        if not pyannote_turns:
            raise Exception("No human voices were detected. Please upload a video containing clear speech.")
            
        logger.info(f"[JOB {job_id}] Stage 2.5: Secondary Speaker Restoration")
        from app.services.vcta.restoration import restore_background_vocals
        restored_bg_wav = str(work_dir / "2-separation" / "Audio_3_Noise_Only_Restored.wav")
        muted_fish_wav = str(work_dir / "2-separation" / "Audio_2_Vocal_Only_Muted.wav")
        
        success = await asyncio.to_thread(
            restore_background_vocals,
            vocals_wav_path=fish_wav,
            instrumental_wav_path=bg_wav,
            output_bg_wav_path=restored_bg_wav,
            output_vocals_wav_path=muted_fish_wav,
            purged_turns=purged_turns
        )
        if success and os.path.exists(restored_bg_wav):
            bg_wav = restored_bg_wav
            fish_wav = muted_fish_wav
            logger.info(f"[JOB {job_id}] Instrumental track restored and Vocals track muted for secondary speakers.")
            
        await database.update_job_status(_get_service_role_client(), workspace_id=workspace_id, job_id=job_id, status="separating", progress=40)

        # Stage 3: The Pristine Slice & Gate
        logger.info(f"[JOB {job_id}] Stage 3: The Pristine Slice & Gate")
        stage3_start = time.time()
        
        grouped_chunks = []
        i = 0
        while i < len(pyannote_turns):
            group = [pyannote_turns[i]]
            group_end = pyannote_turns[i]["end"]
            j = i + 1
            while j < len(pyannote_turns) and pyannote_turns[j]["start"] < group_end:
                group.append(pyannote_turns[j])
                group_end = max(group_end, pyannote_turns[j]["end"])
                j += 1
                
            speakers = list(set(t["speaker"] for t in group))
            is_collision = len(group) > 1 and len(speakers) > 1
            
            grouped_chunks.append({
                "chunk_id": uuid.uuid4().hex,
                "start": group[0]["start"],
                "end": group_end,
                "speakers": speakers,
                "is_collision": is_collision
            })
            i = j
            
        clean_references_ledger = {}
        prepared_tasks = []
        
        for idx, g in enumerate(grouped_chunks, 1):
            duration = g["end"] - g["start"]
            chunk_file = str(dir_chunks / f"chunk_{idx}_audio.wav")
            chunk_video_file = str(dir_chunks / f"chunk_{idx}_video.mp4")
            
            padded_start = max(0.0, g["start"] - 0.2)
            padded_end = g["end"] + 0.2
            padded_duration = padded_end - padded_start
            
            subprocess.run([
                "ffmpeg", "-y", "-i", fish_wav, 
                "-ss", str(padded_start), "-t", str(padded_duration), 
                "-c", "copy", chunk_file
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            subprocess.run([
                "ffmpeg", "-y", "-i", str(video_path), 
                "-ss", str(padded_start), "-t", str(padded_duration), 
                "-c", "copy", chunk_video_file
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            chunk_dict = {
                "chunk_id": g["chunk_id"],
                "file_path": chunk_file,
                "audio_file": chunk_file,
                "start_time_sec": g["start"],
                "end_time_sec": g["end"],
                "duration_sec": duration,
                "speech_duration": duration,
                "start_time": g["start"],
                "end_time": g["end"],
                "speakers": g["speakers"],
                "status": "pending",
                "has_collision": g["is_collision"]
            }
            
            rms_energy = chunker.calculate_rms_energy(chunk_file)
            chunk_dict["raw_rms"] = rms_energy
            
            if not g["is_collision"]:
                chunk_dict["speaker"] = g["speakers"][0]
                spk = chunk_dict["speaker"]
                if spk not in clean_references_ledger:
                    clean_references_ledger[spk] = []
                clean_references_ledger[spk].append((rms_energy, chunk_file))
                logger.info(f"[JOB {job_id}] Saved clean reference for {spk} (RMS: {rms_energy})")
                
            prepared_tasks.append((idx, g, chunk_dict, chunk_file, rms_energy))
            
        stage3_dur = (time.time() - stage3_start) * 1000
        stage3_cost = (stage3_dur / 1000) * PRICING_CPU_PER_SECOND
        total_cost_usd += stage3_cost
        await database.create_step_telemetry(
            _get_service_role_client(),
            workspace_id=workspace_id,
            job_id=job_id,
            chunk_index=-1,
            step_name="Pristine Slice & Gate (FFmpeg)",
            duration_ms=stage3_dur,
            status_code=200,
            compute_provider="local_cpu",
            usage_units=stage3_dur/1000,
            cost_usd=stage3_cost
        )
        
        # --- END OF GPU PHASE ---
        # Zip the work_dir
        zip_path = str(jobs_base / f"{next_id}.zip")
        logger.info(f"[JOB {job_id}] Zipping work_dir to {zip_path}")
        
        state_file = work_dir / "gpu_state.json"
        state = {
            "job_id": job_id,
            "workspace_id": workspace_id,
            "category": category,
            "entity": entity,
            "job_start_time": job_start_time,
            "total_cost_usd": total_cost_usd,
            "next_id": next_id,
            "prepared_tasks": prepared_tasks,
            "clean_references_ledger": clean_references_ledger,
            "fish_wav": fish_wav,
            "bg_wav": bg_wav,
            "video_path": str(video_path),
            "gpu_work_dir": str(work_dir.resolve())
        }
        with open(state_file, "w") as f:
            json.dump(state, f, indent=4)
            
        def zipdir(path, ziph):
            for root, dirs, files in os.walk(path):
                for file in files:
                    ziph.write(os.path.join(root, file), 
                               os.path.relpath(os.path.join(root, file), 
                                               os.path.join(path, '..')))
                                               
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            zipdir(str(work_dir), zipf)
            
        logger.info(f"[JOB {job_id}] GPU Phase complete. Return zip path: {zip_path}")
        return zip_path
        
    except Exception as e:
        logger.exception(f"[JOB {job_id}] GPU Pipeline failed: {e}")
        try:
            target_file = input_path if os.path.exists(input_path) else None
            if target_file:
                import ffmpeg
                import math
                probe = ffmpeg.probe(str(target_file))
                format_info = probe.get("format", {})
                duration = float(format_info.get("duration", 0.0))
                duration_minutes = math.ceil(duration / 60.0)
                if duration_minutes > 0:
                    client = _get_service_role_client()
                    new_bal = await database.add_workspace_minutes(client, workspace_id=workspace_id, minutes=duration_minutes)
                    logger.info(f"[JOB {job_id}] Refunded {duration_minutes} minutes to workspace {workspace_id}. New balance: {new_bal} minutes.")
        except Exception as refund_err:
            logger.error(f"[JOB {job_id}] Failed to refund minutes for workspace {workspace_id}: {refund_err}")
            
        await database.update_job_status(_get_service_role_client(), workspace_id=workspace_id, job_id=job_id, status="failed", error=str(e))
        raise

async def process_video_cpu_phase(zip_path: str):
    # Unzip the payload
    if not os.path.exists(zip_path):
        raise Exception(f"Zip file not found: {zip_path}")
        
    jobs_base = Path("data/jobs/sessions")
    jobs_base.mkdir(parents=True, exist_ok=True)
    
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(str(jobs_base))
        
        # Determine the extracted folder name by looking at the zip contents
        extracted_top_level = None
        for name in zip_ref.namelist():
            parts = Path(name).parts
            if parts:
                extracted_top_level = parts[0]
                break
                
    if extracted_top_level:
        work_dir = jobs_base / extracted_top_level
    else:
        # Fallback if zip is empty or flat
        basename = os.path.basename(zip_path).replace(".zip", "")
        work_dir = jobs_base / basename
    
    state_file = work_dir / "gpu_state.json"
    if not state_file.exists():
        raise Exception(f"State file not found in extracted zip: {state_file}")
        
    with open(state_file, "r") as f:
        state = json.load(f)
        
    job_id = state["job_id"]
    workspace_id = state["workspace_id"]
    category = state["category"]
    entity = state["entity"]
    total_cost_usd = state["total_cost_usd"]
    job_start_time = state["job_start_time"]
    next_id = state["next_id"]
    prepared_tasks = state["prepared_tasks"]
    clean_references_ledger = state["clean_references_ledger"]
    fish_wav = state["fish_wav"]
    bg_wav = state["bg_wav"]
    video_path = state["video_path"]
    
    # Remap stale GPU-machine absolute paths to CPU-local paths.
    # The zip was created on the GPU machine where work_dir had a different
    # absolute path. All stored paths must be rewritten to point at the
    # directory where the zip was just extracted.
    gpu_work_dir_str = state.get("gpu_work_dir", "")
    cpu_work_dir_str = str(work_dir.resolve())
    
    def _remap(path_str: str) -> str:
        """Replace the old GPU work_dir prefix with the CPU work_dir prefix."""
        if gpu_work_dir_str and path_str and path_str.startswith(gpu_work_dir_str):
            return cpu_work_dir_str + path_str[len(gpu_work_dir_str):]
        return path_str
    
    if gpu_work_dir_str and gpu_work_dir_str != cpu_work_dir_str:
        logger.info(f"[CPU PHASE] Remapping GPU paths: {gpu_work_dir_str!r} -> {cpu_work_dir_str!r}")
        fish_wav = _remap(fish_wav)
        bg_wav = _remap(bg_wav)
        video_path = _remap(video_path)
        
        # Remap paths inside prepared_tasks (list of [idx, g, chunk_dict, chunk_file, rms_energy])
        remapped_tasks = []
        for task in prepared_tasks:
            idx, g, chunk_dict, chunk_file, rms_energy = task
            chunk_file = _remap(chunk_file)
            for key in ("audio_file", "file_path", "vocal_file", "voice_reference"):
                if chunk_dict.get(key):
                    chunk_dict[key] = _remap(chunk_dict[key])
            remapped_tasks.append([idx, g, chunk_dict, chunk_file, rms_energy])
        prepared_tasks = remapped_tasks
        
        # Remap paths in clean_references_ledger
        # Format: {speaker: [[rms_energy, path], ...]}
        for spk, refs in clean_references_ledger.items():
            clean_references_ledger[spk] = [
                [rms, _remap(p)] for rms, p in refs
            ]
    
    dir_sep = work_dir / "1-separation"
    dir_chunks = work_dir / "2-chunks"
    dir_transcription = work_dir / "3-transcription"
    dir_translation = work_dir / "4-translation"
    dir_side = work_dir / "5-side_by_side"
    dir_arabic = work_dir / "6-arabic_audio_chunks"
    dir_full_video = work_dir / "7-full_arabic_video_no_noise"
    dir_final = work_dir / "8-final_dubbed_video"
    
    for d in [dir_sep, dir_chunks, dir_transcription, dir_translation, dir_side, dir_arabic, dir_full_video, dir_final]:
        d.mkdir(parents=True, exist_ok=True)
    
    try:
        # STAGE 1 & 4 Parallel Execution
        logger.info(f"[JOB {job_id}] Stage 1 & 4: Parallel Transcription and Quarantine Translation")
        from app.services.video import ai_transcription
        from app.core.sanitizer import sanitize_transcript
        from app.services.video.gemini_diarize import gemini_audio_diarize_and_translate
        
        async def _process_transcription_task(idx, g, chunk_dict, chunk_file, rms_energy):
            nonlocal total_cost_usd
            try:
                if not g["is_collision"]:
                    flash_start = time.time()
                    flash_text = await ai_transcription.transcribe_gemini_flash(chunk_file, history=[])
                    flash_dur = (time.time() - flash_start) * 1000
                    audio_secs = (g["end"] - g["start"])
                    flash_cost = ((audio_secs * 25) / 1000000) * PRICING_GEMINI_INPUT_PER_1M
                    total_cost_usd += flash_cost
                    await database.create_step_telemetry(
                        _get_service_role_client(),
                        workspace_id=workspace_id,
                        job_id=job_id,
                        chunk_index=idx,
                        step_name="Transcription (Gemini Flash)",
                        duration_ms=flash_dur,
                        status_code=200,
                        compute_provider="gemini_api",
                        usage_units=audio_secs * 25,
                        cost_usd=flash_cost
                    )

                    if flash_text:
                        chunk_dict["kurdish_raw"] = sanitize_transcript(flash_text)
                        logger.info(f"Gemini 3 Flash: {flash_text}")
                    else:
                        logger.error(f"[JOB {job_id}] CRITICAL: Transcription failed for chunk {g['chunk_id']}.")
                        chunk_dict["kurdish_raw"] = ""
                        
                    with open(dir_transcription / f"chunk_{idx}_transcription.txt", "w", encoding="utf-8") as f:
                        f.write(chunk_dict.get("kurdish_raw", ""))
                    return [chunk_dict]
                else:
                    logger.info(f"[JOB {job_id}] Stage 4: Quarantine triggered for collision chunk {g['chunk_id']}")
                    quar_start = time.time()
                    result = await asyncio.to_thread(gemini_audio_diarize_and_translate, chunk_file)
                    quar_dur = (time.time() - quar_start) * 1000
                    audio_secs = (g["end"] - g["start"])
                    quar_cost = ((audio_secs * 25) / 1000000) * PRICING_GEMINI_INPUT_PER_1M
                    total_cost_usd += quar_cost
                    await database.create_step_telemetry(
                        _get_service_role_client(),
                        workspace_id=workspace_id,
                        job_id=job_id,
                        chunk_index=idx,
                        step_name="Quarantine Translation (Gemini Pro)",
                        duration_ms=quar_dur,
                        status_code=200,
                        compute_provider="gemini_api",
                        usage_units=audio_secs * 25,
                        cost_usd=quar_cost
                    )

                    sub_chunks = []
                    for spk in g["speakers"]:
                        arabic_text = result.get(f"{spk.lower()}_arabic") or result.get("speaker_0_arabic", "")
                        clean_ref = None
                        if spk in clean_references_ledger and clean_references_ledger[spk]:
                            closest_ref = min(clean_references_ledger[spk], key=lambda x: abs(x[0] - rms_energy))
                            clean_ref = closest_ref[1]
                        if not clean_ref:
                            logger.warning(f"[JOB {job_id}] No clean reference found for {spk}! Using toxic chunk.")
                            clean_ref = chunk_file
                            
                        sub_chunk = chunk_dict.copy()
                        sub_chunk["chunk_id"] = f"{g['chunk_id']}_{spk}"
                        sub_chunk["speaker"] = spk
                        sub_chunk["arabic_text"] = arabic_text
                        sub_chunk["voice_reference"] = clean_ref
                        sub_chunk["status"] = "approved"
                        
                        with open(dir_transcription / f"chunk_{idx}_transcription_{spk}.txt", "w", encoding="utf-8") as f:
                            f.write(sub_chunk.get("arabic_text", ""))
                            
                        sub_chunks.append(sub_chunk)
                    return sub_chunks
            except Exception as e:
                logger.error(f"[JOB {job_id}] Task processing failed for chunk {g['chunk_id']}: {e}")
                chunk_dict["speaker"] = g["speakers"][0]
                chunk_dict["kurdish_raw"] = ""
                return [chunk_dict]

        task_coroutines = [
            _process_transcription_task(idx, g, chunk_dict, chunk_file, rms_energy)
            for (idx, g, chunk_dict, chunk_file, rms_energy) in prepared_tasks
        ]
        
        final_chunks = []
        results = await asyncio.gather(*task_coroutines)
        for res_list in results:
            final_chunks.extend(res_list)

        chunks = final_chunks

        # Stage 6: Translate Clean Chunks
        logger.info(f"[JOB {job_id}] Stage 6: Structured Translation")
        session_state = {"work_dir": str(work_dir)}
        
        stage6_start = time.time()
        from app.services.vcta import translator
        translated_chunks = await translator.batch_translate_text(
            chunks=chunks, 
            category_id=category,
            entity=entity
        )
        stage6_dur = (time.time() - stage6_start) * 1000
        
        words_count = sum(count_words(str(c.get("kurdish_raw", ""))) for c in chunks)
        stage6_cost = (words_count * 1.5 * PRICING_GEMINI_OUTPUT_PER_1M) / 1000000
        total_cost_usd += stage6_cost
        
        await database.create_step_telemetry(
            _get_service_role_client(),
            workspace_id=workspace_id,
            job_id=job_id,
            chunk_index=-1,
            step_name="Structured Translation (Gemini Pro)",
            duration_ms=stage6_dur,
            status_code=200,
            compute_provider="gemini_api",
            usage_units=words_count * 1.5,
            cost_usd=stage6_cost
        )
        
        await database.update_job_status(_get_service_role_client(), workspace_id=workspace_id, job_id=job_id, status="separating", progress=75)

        # Stage 7: VCTA Physics Engine
        logger.info(f"[JOB {job_id}] Stage 7: VCTA Physics Engine (Parallel)")
        from app.worker import _async_process_chunk, _async_assemble_video
        
        async def _run_tts_task(i, chunk):
            nonlocal total_cost_usd
            chunk["chunk_index"] = i
            if chunk.get("status") == "approved" and chunk.get("tts_file"):
                return chunk
                
            try:
                tts_start = time.time()
                res_chunk = await _async_process_chunk(
                    chunk=chunk,
                    session_id=str(next_id),
                    session_state_dict=session_state,
                    video_path=str(video_path),
                    translate_only=False,
                    bypass_initial_translation=True
                )
                tts_dur = (time.time() - tts_start) * 1000
                utf8_bytes = len(str(chunk.get("arabic_text", "")).encode("utf-8"))
                tts_cost = (utf8_bytes / 1000) * PRICING_FISH_AUDIO_PER_1K_BYTES
                total_cost_usd += tts_cost
                
                await database.create_step_telemetry(
                    _get_service_role_client(),
                    workspace_id=workspace_id,
                    job_id=job_id,
                    chunk_index=i,
                    step_name="TTS & Alignment (Fish Audio S2 Pro)",
                    duration_ms=tts_dur,
                    status_code=200,
                    compute_provider="fish_audio_s2_pro",
                    usage_units=utf8_bytes,
                    cost_usd=tts_cost
                )

                return res_chunk
            except Exception as e:
                logger.error(f"[JOB {job_id}] Chunk processing exception: {e}")
                chunk["status"] = "failed"
                return chunk

        tts_tasks = [_run_tts_task(i, chunk) for i, chunk in enumerate(translated_chunks, start=1)]
        final_processed_chunks = await asyncio.gather(*tts_tasks)
        final_processed_chunks.sort(key=lambda x: x.get("start_time_sec", 0.0))

        results_json = work_dir / "job_details.json"
        with open(results_json, "w", encoding="utf-8") as f:
            json.dump(final_processed_chunks, f, ensure_ascii=False, indent=4)
            
        for idx, chunk in enumerate(final_processed_chunks, start=1):
            try:
                k_raw = chunk.get("kurdish_raw", "")
                a_text = chunk.get("arabic_text", "")
                dur = float(chunk.get("duration_sec", 0.0) or chunk.get("speech_duration", 0.0) or 1.0)
                
                k_words = count_words(k_raw)
                a_words = count_words(a_text)
                k_wps = round(k_words / dur, 2) if dur > 0 else 0.0
                
                baseline_wps = 1.90
                target_ratio = 1.0
                sem_ratio = round(a_words / k_words, 2) if k_words > 0 else 1.0
                
                speed_mult = round(a_words / max(1, k_words), 2)
                was_clamped = True if (speed_mult < 0.9 or speed_mult > 1.1) else False
                
                chunk_patch = {
                    "kurdishRaw": k_raw,
                    "arabicText": a_text,
                    "kurdish_word_count": k_words,
                    "kurdish_wps": k_wps,
                    "baseline_wps_used": baseline_wps,
                    "speed_multiplier": speed_mult,
                    "target_ratio_applied": target_ratio,
                    "was_clamped": was_clamped,
                    "final_arabic_word_count": a_words,
                    "semantic_ratio": sem_ratio,
                    "kurdish_syllable_count": count_syllables_approx(k_raw),
                    "final_arabic_syllable_count": count_syllables_approx(a_text),
                    "speaker": chunk.get("speaker", "speaker_0"),
                }
                
                await database.create_chunk(
                    _get_service_role_client(),
                    workspace_id=workspace_id,
                    job_id=job_id,
                    chunk_index=idx,
                    start_time=float(chunk.get("start_time_sec", 0.0)),
                    end_time=float(chunk.get("end_time_sec", 0.0)),
                    status=chunk.get("status", "approved"),
                    patch=chunk_patch
                )
            except Exception as telemetry_err:
                logger.warning(f"[JOB {job_id}] Telemetry save error for chunk {idx}: {telemetry_err}")

        await database.update_job_status(_get_service_role_client(), workspace_id=workspace_id, job_id=job_id, status="separating", progress=90)

        # Stage 8: Final Video Assembly
        logger.info(f"[JOB {job_id}] Stage 8: Final Video Assembly")
        stage8_start = time.time()
        
        await _async_assemble_video(
            results=final_processed_chunks,
            session_id=str(next_id),
            video_path=str(video_path),
            bg_wav=bg_wav
        )
        stage8_dur = (time.time() - stage8_start) * 1000
        stage8_cost = (stage8_dur / 1000) * PRICING_CPU_PER_SECOND
        total_cost_usd += stage8_cost
        await database.create_step_telemetry(
            _get_service_role_client(),
            workspace_id=workspace_id,
            job_id=job_id,
            chunk_index=-1,
            step_name="Final Video Assembly (FFmpeg)",
            duration_ms=stage8_dur,
            status_code=200,
            compute_provider="local_cpu",
            usage_units=stage8_dur/1000,
            cost_usd=stage8_cost
        )
        
        output_filename = f"dubbed_{str(next_id)}.mp4"
        final_mp4 = work_dir / "assembled" / "final_dubbed.mp4"
        public_path = Path(f"static/outputs/{output_filename}")
        public_path.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        if os.path.exists(final_mp4):
            shutil.copy(final_mp4, str(public_path))
            
            # Upload to Cloudflare R2
            from app.services import r2
            if r2.R2_ENDPOINT and r2.R2_BUCKET:
                r2_key = r2.dubbing_key(workspace_id, job_id, output_filename)
                await asyncio.to_thread(r2.upload_file, r2_key, str(public_path), "video/mp4")
                output_path_for_db = r2_key
                
                # Clean up local storage after successful upload to R2
                try:
                    shutil.rmtree(work_dir, ignore_errors=True)
                    if os.path.exists(public_path):
                        os.remove(public_path)
                    logger.info(f"[JOB {job_id}] Cleaned up local files to save space.")
                except Exception as e:
                    logger.warning(f"[JOB {job_id}] Failed to clean up local files: {e}")
            else:
                output_path_for_db = f"/static/outputs/{output_filename}"
        else:
            output_path_for_db = f"/static/outputs/{output_filename}"
        
        await database.update_job_status(_get_service_role_client(), workspace_id=workspace_id, job_id=job_id, status="completed", progress=100, output_path=output_path_for_db)
        
        job_total_latency_ms = (time.time() - job_start_time) * 1000
        await database.update_job_cost(
            _get_service_role_client(),
            workspace_id=workspace_id,
            job_id=job_id,
            total_latency_ms=job_total_latency_ms,
            total_cost_usd=total_cost_usd
        )
        logger.info(f"[JOB {job_id}] Completed successfully. Latency: {job_total_latency_ms:.1f}ms, Cost: ${total_cost_usd:.4f}")

    except Exception as e:
        logger.exception(f"[JOB {job_id}] Pipeline failed: {e}")
        await database.update_job_status(_get_service_role_client(), workspace_id=workspace_id, job_id=job_id, status="failed", error=str(e))
        raise


async def process_video_job_local(job_id: str, input_path: str, workspace_id: str = "", category: str = None, entity: str = None):
    zip_path = await process_video_gpu_phase(job_id, input_path, workspace_id, category, entity)
    await process_video_cpu_phase(zip_path)
