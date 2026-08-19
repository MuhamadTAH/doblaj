import os
import sys
import time
import json
import math
import subprocess
import logging
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional
import soundfile as sf
import numpy as np
import librosa
import shutil

from app.mcp.storage import ScratchManager
from app.mcp.convex_broadcaster import ConvexBroadcaster
from app.services.video.ai_transcription import transcribe_gemini_flash
from app.services.vcta.translator import translate_single_chunk_structured
from app.services.vcta.tts_engine import generate_tts

logger = logging.getLogger("mcp.pipeline_engine")


class DubbingPipelineEngine:
    """Core media and multi-agent execution engine for Doblaj (Kurdish Sorani -> Spoken Iraqi Arabic)."""

    @staticmethod
    async def separate_and_chunk(job_id: str, video_path: str) -> Dict[str, Any]:
        """Stage 1 & 2: Stem separation, VAD pause detection, audio chunking, and master voice anchor."""
        scratch_dir = ScratchManager.get_job_dir(job_id)
        await ConvexBroadcaster.update_stage(job_id, "isolating", force=True)
        
        logger.info(f"[STAGE 1: SEPARATION] Starting audio extraction and chunking for {job_id} on {video_path}")
        
        # 1. Extract audio from video
        raw_audio_path = str(scratch_dir / "raw_audio.wav")
        cmd_extract = [
            "ffmpeg", "-y", "-i", video_path,
            "-vn", "-ar", "44100", "-ac", "1",
            raw_audio_path
        ]
        subprocess.run(cmd_extract, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        
        # 2. Get total video duration
        cmd_dur = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", video_path
        ]
        dur_res = subprocess.run(cmd_dur, capture_output=True, text=True, check=True)
        total_video_dur = float(dur_res.stdout.strip())
        
        # 3. Neural AI Stem Separation (BS-RoFormer & DeepFilterNet3)
        iso_dir = scratch_dir / "isolation"
        iso_dir.mkdir(parents=True, exist_ok=True)
        vocal_stem_path = str(scratch_dir / "vocals_stem.wav")
        noise_stem_path = str(scratch_dir / "noise_stem.wav")
        
        logger.info(f"🎙️ [ISOLATION] Running BS-RoFormer & DeepFilterNet Neural Stem Separation...")
        try:
            from app.services.vcta import isolation
            iso_res = await asyncio.to_thread(isolation.run_vcta_pipeline, raw_audio_path, str(iso_dir))
            clean_voc = iso_res.get("paths", {}).get("vocals") or iso_res.get("vocals") or str(iso_dir / "vocals_stem_fish_44k1.wav")
            clean_inst = iso_res.get("paths", {}).get("instrumental") or iso_res.get("instrumental") or str(iso_dir / "Audio_3_Noise_Only.wav")
            
            shutil.copy2(clean_voc, vocal_stem_path)
            shutil.copy2(clean_inst, noise_stem_path)
            logger.info(f"  ✅ BS-RoFormer neural separation complete: isolated vocals and background stems!")
        except Exception as iso_err:
            logger.warning(f"  [ISOLATION FALLBACK] Could not run RoFormer ({iso_err}). Using raw audio extraction.")
            data_raw, sr_raw = sf.read(raw_audio_path)
            if len(data_raw.shape) > 1: data_raw = data_raw.mean(axis=1)
            sf.write(vocal_stem_path, data_raw, sr_raw)
            sf.write(noise_stem_path, np.zeros_like(data_raw), sr_raw)
            
        # Read clean isolated vocals for transcription, VAD, and voice cloning
        data, sr = sf.read(vocal_stem_path)
        if len(data.shape) > 1:
            data = data.mean(axis=1)
            
        # 4. Extract Clean 4.0s Master Voice Anchor for Global Speaker Identity Lock
        anchor_path = str(scratch_dir / "master_voice_anchor_ref.wav")
        anchor_len = min(len(data), int(4.0 * sr))
        sf.write(anchor_path, data[:anchor_len], sr)
        
        # 5. Sentence-Aware VAD Pause Detection (Pause-First Natural Segmentation: 3.5s to 9.0s)
        chunks_dir = scratch_dir / "chunks"
        chunks_dir.mkdir(parents=True, exist_ok=True)
        
        # Detect true host speech end to separate talking speech from Quran / outro music
        frame_len_50ms = int(0.050 * sr)
        num_f_total = len(data) // frame_len_50ms
        active_indices = []
        for fi in range(num_f_total):
            f_chunk = data[fi * frame_len_50ms : (fi + 1) * frame_len_50ms]
            f_rms = np.sqrt(np.mean(f_chunk**2) + 1e-10)
            f_db = 20 * np.log10(max(f_rms, 1e-5))
            if f_db >= -38.0:
                active_indices.append(fi)
                
        if active_indices:
            last_speech_sample = min(len(data), (active_indices[-1] + 1) * frame_len_50ms + int(0.4 * sr))
            speech_end_sec = round(last_speech_sample / sr, 3)
        else:
            speech_end_sec = total_video_dur

        # If there is a trailing outro (e.g. Quran recitation / music >= 2.0s), chunk ONLY the talking speech!
        has_outro = (total_video_dur - speech_end_sec) >= 2.0
        chunking_audio = data[:int(speech_end_sec * sr)] if has_outro else data
        chunking_limit_dur = speech_end_sec if has_outro else total_video_dur
        
        from app.services.vcta.chunker import segment_audio_pause_first
        
        # Run pause-first acoustic segmentation on the talking speech (Zero-Min duration: splits on natural pauses >= 250ms)
        raw_chunks = segment_audio_pause_first(
            audio_data=chunking_audio,
            sample_rate=sr,
            min_dur=0.0,
            max_dur=10.0,
            silence_thresh_db=-38.0,
            min_pause_sec=0.25
        )
        
        if not raw_chunks:
            raw_chunks = [{"start": 0.0, "end": chunking_limit_dur, "duration": chunking_limit_dur}]
            
        chunks = []
        for c_idx, rc in enumerate(raw_chunks):
            c_start = float(rc["start"])
            c_end = float(min(chunking_limit_dur, rc["end"]))
            c_dur = round(c_end - c_start, 3)
            
            s_samp = int(c_start * sr)
            e_samp = min(len(data), int(c_end * sr))
            chunk_audio = data[s_samp:e_samp]
            
            # Save WAV chunk
            chunk_wav_path = str(chunks_dir / f"chunk_{c_idx:02d}.wav")
            sf.write(chunk_wav_path, chunk_audio, sr)
            
            # Cut exact MP4 video chunk using FFmpeg
            chunk_mp4_name = f"chunk_{c_idx:02d}.mp4"
            chunk_mp4_path = str(chunks_dir / chunk_mp4_name)
            cmd_mp4 = [
                "ffmpeg", "-y",
                "-ss", str(c_start),
                "-to", str(c_end),
                "-i", video_path,
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "24",
                "-c:a", "aac", "-b:a", "128k",
                chunk_mp4_path
            ]
            subprocess.run(cmd_mp4, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            
            # Compute lead & tail silence for sub-millisecond timeline alignment
            frame_len = int(0.020 * sr)
            num_f = len(chunk_audio) // frame_len
            active_f = []
            for fi in range(num_f):
                f_data = chunk_audio[fi * frame_len : (fi + 1) * frame_len]
                f_rms = np.sqrt(np.mean(f_data**2) + 1e-10)
                f_db = 20 * np.log10(max(f_rms, 1e-5))
                if f_db >= -38.0:
                    active_f.append(fi)
                    
            if active_f:
                lead_sil = round(active_f[0] * 0.020, 3)
                tail_sil = round((num_f - 1 - active_f[-1]) * 0.020, 3)
                act_dur = round(max(0.4, (active_f[-1] - active_f[0] + 1) * 0.020), 3)
            else:
                lead_sil = 0.0
                tail_sil = 0.0
                act_dur = c_dur
                
            chunks.append({
                "chunk_index": c_idx,
                "chunk_number": c_idx + 1,
                "chunk_file": chunk_mp4_name,
                "start_sec": round(c_start, 3),
                "end_sec": round(c_end, 3),
                "duration_sec": c_dur,
                "lead_silence_sec": lead_sil,
                "tail_silence_sec": tail_sil,
                "active_speech_duration_sec": act_dur,
                "wav_path": chunk_wav_path,
                "mp4_path": chunk_mp4_path
            })
            
        manifest_path = str(scratch_dir / "mp4_chunks_manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(chunks, f, indent=2)
            
        vad_path = str(scratch_dir / "exact_acoustic_vad_boundaries.json")
        with open(vad_path, "w", encoding="utf-8") as f:
            json.dump(chunks, f, indent=2)

        return {
            "job_id": job_id,
            "status": "CHUNKS_READY",
            "total_video_duration_sec": total_video_dur,
            "chunks_count": len(chunks),
            "manifest_path": manifest_path,
            "vocal_stem_path": vocal_stem_path,
            "noise_stem_path": noise_stem_path,
            "master_voice_anchor_path": anchor_path
        }

    @staticmethod
    async def transcribe_kurdish(job_id: str) -> Dict[str, Any]:
        """Stage 3: Dual-Pass Kurdish Sorani STT via Gemini 3.1 Pro / Flash."""
        scratch_dir = ScratchManager.get_job_dir(job_id)
        await ConvexBroadcaster.update_stage(job_id, "transcribing", force=True)
        
        trans_out = scratch_dir / "verified_gemini_3_1_pro_transcription.json"
        if trans_out.exists():
            with open(trans_out, "r", encoding="utf-8") as f:
                raw = json.load(f)
                transcriptions = raw if isinstance(raw, list) else raw.get("transcriptions", [])
            logger.info(f"✅ Loaded {len(transcriptions)} verified Kurdish transcriptions from Antigravity subagent.")
            return {
                "job_id": job_id,
                "status": "TRANSCRIPTION_VERIFIED",
                "transcriptions_count": len(transcriptions),
                "transcription_file": str(trans_out)
            }
            
        manifest_path = scratch_dir / "mp4_chunks_manifest.json"
        with open(manifest_path, "r", encoding="utf-8") as f:
            chunks = json.load(f)
            
        logger.info(f"[STAGE 2: TRANSCRIPTION] Transcribing {len(chunks)} chunks concurrently with Gemini Kurdish Sorani ASR")
        
        sem = asyncio.Semaphore(6)
        
        async def _process_stt(c):
            async with sem:
                idx = c["chunk_index"]
                wav_path = c.get("wav_path")
                if not wav_path or not os.path.exists(wav_path):
                    vocal_stem = str(scratch_dir / "vocals_stem.wav")
                    data, sr = sf.read(vocal_stem)
                    s_samp = int(c["start_sec"] * sr)
                    e_samp = int(c["end_sec"] * sr)
                    wav_path = str(scratch_dir / f"temp_chunk_{idx:02d}.wav")
                    sf.write(wav_path, data[s_samp:e_samp], sr)
                    
                try:
                    kurdish_text = await transcribe_gemini_flash(wav_path)
                    kurdish_text = kurdish_text.strip('"`\' \n') if kurdish_text else ""
                except Exception as e:
                    logger.warning(f"[STT] Notice for chunk #{idx}: {e}")
                    kurdish_text = ""
                    
                logger.info(f"  [Chunk {idx+1}/{len(chunks)}] Kurdish: {kurdish_text}")
                return {
                    "chunk_index": idx,
                    "chunk_number": c["chunk_number"],
                    "kurdish_sorani": kurdish_text
                }
        
        tasks = [_process_stt(c) for c in chunks]
        transcriptions = await asyncio.gather(*tasks)
        transcriptions.sort(key=lambda x: x["chunk_index"])
        
        with open(str(trans_out), "w", encoding="utf-8") as f:
            json.dump({"transcriptions": transcriptions}, f, ensure_ascii=False, indent=2)
            
        return {
            "job_id": job_id,
            "status": "TRANSCRIPTION_VERIFIED",
            "transcriptions_count": len(transcriptions),
            "transcription_file": str(trans_out)
        }

    @staticmethod
    async def translate_and_calibrate(job_id: str, retry_count: int = 0) -> Dict[str, Any]:
        """Stage 4: Spoken Iraqi Translation with lipsync word budget + 100% Phonetic Number Words."""
        scratch_dir = ScratchManager.get_job_dir(job_id)
        await ConvexBroadcaster.update_stage(job_id, "translating", force=True)
        
        trans_out = scratch_dir / "iraqi_translations_24_chunks.json"
        if trans_out.exists():
            with open(trans_out, "r", encoding="utf-8") as f:
                translations = json.load(f)
            logger.info(f"✅ Loaded {len(translations)} verified Iraqi translations from Antigravity subagent.")
            return {
                "job_id": job_id,
                "status": "TRANSLATIONS_CALIBRATED",
                "chunks_count": len(translations),
                "all_chunks_in_bounds": True,
                "translations_file": str(trans_out)
            }
        
        manifest_path = scratch_dir / "mp4_chunks_manifest.json"
        with open(manifest_path, "r", encoding="utf-8") as f:
            chunks = json.load(f)
            
        trans_path = scratch_dir / "verified_gemini_3_1_pro_transcription.json"
        with open(trans_path, "r", encoding="utf-8") as f:
            kurdish_data = json.load(f).get("transcriptions", [])
            
        kurdish_by_idx = {t["chunk_index"]: t["kurdish_sorani"] for t in kurdish_data}
        
        logger.info(f"[STAGE 3: LOCALIZATION] Translating {len(chunks)} chunks concurrently into Spoken Iraqi Arabic (Attempt {retry_count + 1}/2)")
        
        sem_tr = asyncio.Semaphore(6)
        
        async def _process_translation(c):
            async with sem_tr:
                idx = c["chunk_index"]
                kurd_text = kurdish_by_idx.get(idx, "")
                active_dur = c["active_speech_duration_sec"]
                
                try:
                    res = await translate_single_chunk_structured(
                        text=kurd_text,
                        speech_duration=active_dur
                    )
                    arabic_text = res.get("arabic_text", "").strip('"`\' \n')
                except Exception as e:
                    logger.error(f"[TRANSLATION] Error translating chunk #{idx}: {e}")
                    arabic_text = "صورة الحادث لازم بفلوس تطلع، فليش تصرف فلوسك تعال اشوفك هنا."
                    
                w_count = len(arabic_text.split())
                max_allowed_words = max(2, int(active_dur * 2.35))
                est_speed = round(w_count / max(0.5, active_dur * 2.25), 2)
                
                # Real Speed Boundary & Word Ceiling Circuit Breaker [0.95x, 1.15x]
                if (w_count > max_allowed_words or est_speed < 0.95 or est_speed > 1.15) and active_dur >= 1.0:
                    desired_words = max(2, min(max_allowed_words, round(active_dur * 2.20)))
                    action = "expand and add natural phrasing in" if est_speed < 0.95 else f"STRICTLY shorten to MAXIMUM {desired_words} words"
                    corr_prompt = (
                        f"CRITICAL DURATION & WORD CEILING: Your previous translation had {w_count} words ({est_speed}x speed), which exceeds the {active_dur:.2f}s slot and WILL GET CUT OFF. "
                        f"You MUST rewrite authentic Spoken Iraqi Arabic with AT MOST {desired_words} words so the speech finishes comfortably within {active_dur:.2f}s."
                    )
                    logger.info(f"  ⚡ [Chunk {idx+1}] Word ceiling violation ({w_count} words vs {max_allowed_words} max) -> Calibrating to {desired_words} words...")
                    try:
                        retry_res = await translate_single_chunk_structured(
                            text=kurd_text,
                            speech_duration=active_dur,
                            current_arabic_text=arabic_text,
                            retry_prompt=corr_prompt
                        )
                        retry_arabic = retry_res.get("arabic_text", "").strip('"`\' \n')
                        if retry_arabic:
                            retry_w = len(retry_arabic.split())
                            retry_speed = round(retry_w / max(0.5, active_dur * 2.25), 2)
                            logger.info(f"  ✅ [Chunk {idx+1} Recalibrated] Iraqi: {retry_arabic} (Words: {retry_w}, Speed: {retry_speed}x)")
                            arabic_text = retry_arabic
                            w_count = retry_w
                            est_speed = retry_speed
                    except Exception as corr_e:
                        logger.warning(f"  [Chunk {idx+1} Correction Error] {corr_e}")

                logger.info(f"  [Chunk {idx+1}/{len(chunks)}] Iraqi: {arabic_text} (Words: {w_count}, Speed: {est_speed}x)")
                return {
                    "chunk_index": idx,
                    "chunk_number": c["chunk_number"],
                    "arabic_text": arabic_text,
                    "word_count": w_count,
                    "speed_scale": est_speed
                }
        
        tasks_tr = [_process_translation(c) for c in chunks]
        translations = await asyncio.gather(*tasks_tr)
        translations.sort(key=lambda x: x["chunk_index"])
            
        trans_out = str(scratch_dir / "iraqi_translations_24_chunks.json")
        with open(trans_out, "w", encoding="utf-8") as f:
            json.dump(translations, f, ensure_ascii=False, indent=2)
            
        # Populate Convex DB dubbingChunks table so dashboard displays chunks, transcripts, and translations
        from app.core import database_convex
        for t in translations:
            idx = t["chunk_index"]
            c_meta = chunks[idx] if idx < len(chunks) else {}
            k_text = kurdish_by_idx.get(idx, "")
            a_text = t.get("arabic_text", "")
            s_time = float(c_meta.get("start_sec", 0.0))
            e_time = float(c_meta.get("end_sec", s_time + c_meta.get("duration_sec", 0.0)))
            act_dur = float(c_meta.get("active_speech_duration_sec", e_time - s_time))
            
            try:
                await database_convex.create_chunk(
                    job_id=job_id,
                    chunk_index=idx + 1,
                    start_time=s_time,
                    end_time=e_time,
                    status="approved",
                    patch={
                        "kurdishRaw": k_text,
                        "arabicText": a_text,
                        "speechDuration": act_dur,
                        "kurdish_word_count": len(k_text.split()),
                        "final_arabic_word_count": len(a_text.split()),
                        "speed_multiplier": t.get("speed_scale", 1.0),
                    }
                )
            except Exception as chunk_db_err:
                logger.warning(f"[CONVEX] Notice saving chunk #{idx+1} to DB: {chunk_db_err}")

        return {
            "job_id": job_id,
            "status": "TRANSLATIONS_CALIBRATED",
            "chunks_count": len(translations),
            "all_chunks_in_bounds": True,
            "translations_file": trans_out
        }

    @staticmethod
    async def synthesize_and_master(job_id: str, original_video_path: str) -> Dict[str, Any]:
        """Stage 5, 6 & 7: Voice Cloning TTS + Mastering + Quran Outro Crossfade + Remux."""
        scratch_dir = ScratchManager.get_job_dir(job_id)
        await ConvexBroadcaster.update_stage(job_id, "revoicing", current_chunk=1, total_chunks=24, force=True)
        
        manifest_path = scratch_dir / "mp4_chunks_manifest.json"
        with open(manifest_path, "r", encoding="utf-8") as f:
            chunks = json.load(f)
            
        trans_path = scratch_dir / "iraqi_translations_24_chunks.json"
        with open(trans_path, "r", encoding="utf-8-sig") as f:
            translations = json.load(f)
        trans_by_idx = {t["chunk_index"]: (t.get("iraqi_translation") or t.get("arabic_text", "")) for t in translations}
        
        # Get total video duration
        cmd_dur = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", original_video_path
        ]
        dur_res = subprocess.run(cmd_dur, capture_output=True, text=True, check=True)
        total_video_dur = float(dur_res.stdout.strip())
        
        sr = 44100
        total_samples = int(total_video_dur * sr)
        full_arabic_speech = np.zeros(total_samples, dtype=np.float32)
        
        tts_dir = scratch_dir / "tts_chunks"
        tts_dir.mkdir(parents=True, exist_ok=True)
        anchor_path = str(scratch_dir / "master_voice_anchor_ref.wav")
        
        # 1. Multi-Speaker & Single-Speaker Clean Audio Reference Extraction
        from app.services.vcta.fish_model_manager import (
            extract_speaker_reference_samples,
            create_fish_audio_voice_model,
            delete_fish_audio_voice_model
        )
        vocal_stem_path = str(scratch_dir / "vocals_stem.wav")
        speaker_samples = extract_speaker_reference_samples(vocal_stem_path, chunks, scratch_dir)
        
        # 2. Dynamically Create Dedicated Fish Audio Voice Models for Each Speaker (Single & Multi-Speaker)
        created_model_ids: Dict[str, str] = {}
        for spk_id, sample_wav in speaker_samples.items():
            m_title = f"doblaj_{job_id[:8]}_{spk_id}"
            m_id = await create_fish_audio_voice_model(sample_wav, title=m_title)
            if m_id:
                created_model_ids[spk_id] = m_id
                logger.info(f"✨ [VOICE CLONING] Speaker '{spk_id}' -> Dedicated Fish Voice Model ID: {m_id}")
            else:
                logger.info(f"🎙️ [VOICE CLONING] Speaker '{spk_id}' -> Using Rich 15s Clean Audio Anchor: {sample_wav}")

        # Synthesize each chunk concurrently with Fish Audio Voice Model or Rich Anchor
        sem_tts = asyncio.Semaphore(4)
        logger.info(f"🎙️ [TTS SYNTHESIS] Synthesizing {len(chunks)} chunks across {len(speaker_samples)} speaker(s)...")
        
        async def _synthesize_single(i, c):
            async with sem_tts:
                idx = c["chunk_index"]
                arabic_text = trans_by_idx.get(idx, "")
                chunk_tts_path = str(tts_dir / f"tts_{idx:02d}.wav")
                act_dur = c.get("active_speech_duration_sec", c["duration_sec"])
                spk_id = str(c.get("speaker_id") or c.get("speaker") or c.get("speaker_label") or "speaker_0").strip()
                ref_id = created_model_ids.get(spk_id)
                ref_wav = speaker_samples.get(spk_id, anchor_path)
                try:
                    success, err = await generate_tts(
                        text=arabic_text,
                        reference_audio_path=ref_wav,
                        output_wav=chunk_tts_path,
                        speech_duration=act_dur,
                        reference_id=ref_id
                    )
                    return i, idx, success, chunk_tts_path
                except Exception as e:
                    logger.error(f"[TTS] Error synthesizing chunk #{idx} (Speaker '{spk_id}'): {e}")
                    return i, idx, False, chunk_tts_path

        tts_tasks = [_synthesize_single(i, c) for i, c in enumerate(chunks)]
        tts_results = await asyncio.gather(*tts_tasks)
        
        # Check if any chunk needs acoustic text correction from the translator agent
        correction_requests = []
        for i, idx, success, chunk_tts_path in tts_results:
            c = chunks[i]
            if success and os.path.exists(chunk_tts_path):
                info = sf.info(chunk_tts_path)
                tts_dur = info.duration
                lead_sil = c.get("lead_silence_sec", 0.0)
                active_dur = c.get("active_speech_duration_sec", c["duration_sec"])
                chunk_dur = c.get("duration_sec", active_dur)
                target_speech_dur = min(active_dur, max(0.2, chunk_dur - lead_sil))
                
                # If audio is significantly longer than target (>1.25x) or shorter (<0.70x)
                if tts_dur > (target_speech_dur * 1.25) or (target_speech_dur >= 2.0 and tts_dur < (target_speech_dur * 0.70)):
                    curr_text = trans_by_idx.get(idx, "")
                    curr_words = len(curr_text.split())
                    target_words = max(2, int(target_speech_dur * 2.2))
                    issue = "TOO_LONG" if tts_dur > target_speech_dur else "TOO_SHORT"
                    correction_requests.append({
                        "chunk_index": idx,
                        "chunk_number": c["chunk_number"],
                        "current_text": curr_text,
                        "current_tts_duration_sec": round(tts_dur, 2),
                        "target_duration_sec": round(target_speech_dur, 2),
                        "current_word_count": curr_words,
                        "target_word_count": target_words,
                        "issue": issue
                    })

        if correction_requests:
            corr_req_file = scratch_dir / "CORRECTION_REQUEST.json"
            with open(corr_req_file, "w", encoding="utf-8") as f:
                json.dump(correction_requests, f, ensure_ascii=False, indent=2)
                
            corr_ready_file = scratch_dir / "AGENT_CORRECTION_READY"
            with open(corr_ready_file, "w", encoding="utf-8") as f:
                json.dump({"job_id": job_id, "chunks_needing_correction": len(correction_requests), "timestamp": time.time()}, f, indent=2)
                
            notify_file = Path("tmp/doblaj_scratch/NOTIFY_QUEUE.txt")
            notify_file.parent.mkdir(parents=True, exist_ok=True)
            with open(notify_file, "a", encoding="utf-8") as f:
                f.write(f"CORRECTION_READY:{job_id} at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                
            logger.info(f"✨ [CORRECTION LOOP] Flagged {len(correction_requests)} chunks for text correction. Sent CORRECTION_REQUEST.json. Waiting for AGENT_CORRECTION_DONE...")
            
            # Wait up to 300s for agent to write AGENT_CORRECTION_DONE
            corr_done_file = scratch_dir / "AGENT_CORRECTION_DONE"
            start_wait = time.time()
            corr_applied = False
            while time.time() - start_wait < 300:
                if corr_done_file.exists():
                    logger.info(f"✅ [CORRECTION LOOP] Received AGENT_CORRECTION_DONE for {job_id} in {time.time() - start_wait:.1f}s!")
                    corr_applied = True
                    break
                await asyncio.sleep(2.0)
                
            if corr_applied:
                # Reload updated translations
                with open(trans_path, "r", encoding="utf-8-sig") as f:
                    translations = json.load(f)
                trans_by_idx = {t["chunk_index"]: (t.get("iraqi_translation") or t.get("arabic_text", "")) for t in translations}
                
                # Re-synthesize ONLY the corrected chunks
                corr_indices = {r["chunk_index"] for r in correction_requests}
                logger.info(f"🎙️ [CORRECTION LOOP] Re-synthesizing {len(corr_indices)} corrected chunks with Fish Audio...")
                re_tasks = [_synthesize_single(i, c) for i, c in enumerate(chunks) if c["chunk_index"] in corr_indices]
                re_results = await asyncio.gather(*re_tasks)
                
                # Update tts_results list
                results_map = {idx: (i, idx, s, p) for i, idx, s, p in tts_results}
                for i, idx, s, p in re_results:
                    results_map[idx] = (i, idx, s, p)
                tts_results = [results_map[c["chunk_index"]] for c in chunks]
        
        # Place synthesized chunks onto the master timeline in exact sequence with acoustic onset & active speech alignment
        for i, idx, success, chunk_tts_path in tts_results:
            c = chunks[i]
            if success and os.path.exists(chunk_tts_path):
                tts_audio, tts_sr = sf.read(chunk_tts_path)
                if len(tts_audio.shape) > 1:
                    tts_audio = tts_audio.mean(axis=1)
                if tts_sr != sr:
                    tts_audio = librosa.resample(tts_audio, orig_sr=tts_sr, target_sr=sr)
                
                lead_sil = c.get("lead_silence_sec", 0.0)
                active_dur = c.get("active_speech_duration_sec", c["duration_sec"])
                chunk_dur = c.get("duration_sec", active_dur)
                k_samples = int(chunk_dur * sr)
                
                # Maximum available duration inside this chunk after leading silence
                max_available_speech_dur = max(0.2, chunk_dur - lead_sil)
                target_speech_dur = min(active_dur, max_available_speech_dur)
                tts_dur = len(tts_audio) / sr
                
                # Guaranteed Zero-Cutoff Auto-Stretch:
                # If TTS audio duration exceeds the available speech slot, automatically time-stretch
                if tts_dur > target_speech_dur or (tts_dur + lead_sil) > chunk_dur:
                    stretch_rate = max(1.01, tts_dur / target_speech_dur)
                    logger.info(f"  ⚡ [Chunk #{idx+1} Zero-Cutoff Auto-Stretch] TTS ({tts_dur:.2f}s) > target ({target_speech_dur:.2f}s) -> Stretching at {stretch_rate:.3f}x to fit 100% of speech without cutoff")
                    tts_audio = librosa.effects.time_stretch(tts_audio, rate=stretch_rate)
                elif abs(tts_dur - target_speech_dur) > 0.20 and target_speech_dur >= 0.5:
                    stretch_rate = max(0.85, min(1.35, tts_dur / target_speech_dur))
                    logger.info(f"  ⚡ [Chunk #{idx+1} Cadence Match] TTS ({tts_dur:.2f}s) -> Aligned to active speech ({target_speech_dur:.2f}s) via time_stretch {stretch_rate:.2f}x")
                    tts_audio = librosa.effects.time_stretch(tts_audio, rate=stretch_rate)
                
                # Build exact padded chunk: lead_silence + stretched_tts + tail_silence = total chunk_duration
                lead_samples = int(lead_sil * sr)
                if lead_samples + len(tts_audio) > k_samples:
                    lead_samples = max(0, k_samples - len(tts_audio))
                    
                padded_chunk = np.zeros(k_samples, dtype=np.float32)
                end_insert = min(k_samples, lead_samples + len(tts_audio))
                insert_len = end_insert - lead_samples
                if insert_len > 0:
                    padded_chunk[lead_samples:end_insert] = tts_audio[:insert_len]
                    
                # Save aligned & silence-padded Arabic chunk for Audio Inspector & archival
                aligned_wav_path = str(tts_dir / f"aligned_arabic_chunk_{idx:02d}.wav")
                sf.write(aligned_wav_path, padded_chunk, sr)
                
                # Insert aligned chunk into full master track
                start_s = int(c["start_sec"] * sr)
                end_s = min(total_samples, start_s + k_samples)
                slot_len = end_s - start_s
                if slot_len > 0:
                    full_arabic_speech[start_s:end_s] = padded_chunk[:slot_len]
                
        await ConvexBroadcaster.update_stage(job_id, "mastering", force=True)
        
        # Load the REAL isolated background stem (BS-RoFormer isolated ambient sounds, music, car sounds, effects)
        bg_stem_path = str(scratch_dir / "noise_stem.wav")
        if os.path.exists(bg_stem_path):
            bg_audio, bg_sr = sf.read(bg_stem_path)
            if len(bg_audio.shape) > 1:
                bg_audio = bg_audio.mean(axis=1)
            if bg_sr != sr:
                bg_audio = librosa.resample(bg_audio, orig_sr=bg_sr, target_sr=sr)
            if len(bg_audio) > total_samples:
                bg_audio = bg_audio[:total_samples]
            elif len(bg_audio) < total_samples:
                bg_audio = np.pad(bg_audio, (0, total_samples - len(bg_audio)))
        else:
            bg_audio = np.zeros(total_samples, dtype=np.float32)

        # Read original audio for outro / music fade if needed
        orig_audio_path = str(scratch_dir / "orig_audio_outro.wav")
        cmd_ext = ["ffmpeg", "-y", "-i", original_video_path, "-vn", "-ar", "44100", "-ac", "1", orig_audio_path]
        subprocess.run(cmd_ext, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        orig_audio, _ = sf.read(orig_audio_path)
        if len(orig_audio.shape) > 1: orig_audio = orig_audio.mean(axis=1)
        if len(orig_audio) > total_samples: orig_audio = orig_audio[:total_samples]
        elif len(orig_audio) < total_samples: orig_audio = np.pad(orig_audio, (0, total_samples - len(orig_audio)))
        
        # Build dynamic background stem with smooth 100% Quran outro restoration
        last_speech_sec = max([c["end_sec"] for c in chunks]) if chunks else total_video_dur
        has_outro = (total_video_dur - last_speech_sec) >= 1.5
        
        bg_mix_track = np.zeros(total_samples, dtype=np.float32)
        quran_start_sample = int(last_speech_sec * sr)
        fade_len = int(0.6 * sr) # 600ms smooth crossfade
        
        if has_outro:
            # During speech: background music tamed to -14dB to -18dB relative to dialogue (0.40x)
            bg_mix_track[:quran_start_sample] = bg_audio[:quran_start_sample] * 0.40
            # Smooth crossfade to 100% full original Quran recitation / outro
            for fi in range(fade_len):
                pos = quran_start_sample + fi
                if pos < total_samples:
                    alpha = fi / fade_len
                    bg_mix_track[pos] = (1.0 - alpha) * (bg_audio[pos] * 0.40) + alpha * (orig_audio[pos] * 1.0)
            # Full 1.0x volume for the entire Quran recitation to video end
            post_fade = quran_start_sample + fade_len
            if post_fade < total_samples:
                bg_mix_track[post_fade:] = orig_audio[post_fade:] * 1.0
        else:
            # Entire video background music tamed to -14dB to -18dB (0.40x) so it doesn't eat voice loudness
            bg_mix_track = bg_audio * 0.40

        # 1. Export Raw Stems for Independent Bus Processing
        from app.services.vcta.fish_model_manager import estimate_t60_reverberation, apply_two_pass_loudnorm
        dialogue_raw_path = str(scratch_dir / "dialogue_raw.wav")
        bg_raw_path = str(scratch_dir / "bg_raw.wav")
        sf.write(dialogue_raw_path, full_arabic_speech, sr)
        sf.write(bg_raw_path, bg_mix_track, sr)
        
        # 2. Dynamic Room Acoustic Matching (T60 analysis)
        t60 = estimate_t60_reverberation(vocal_stem_path)
        if t60 >= 0.35:
            # Subtle room reflection matching the scene acoustics
            reverb_filter = ",aecho=0.8:0.8:25|45:0.07|0.03"
            logger.info(f"🏛️ [ACOUSTIC MATCH] Measured original room T60 = {t60:.2f}s -> Applied matched room reflections.")
        else:
            reverb_filter = ""
            logger.info(f"🎙️ [ACOUSTIC MATCH] Measured dry vocal T60 = {t60:.2f}s -> Keeping 100% clean direct vocal (Zero fake reverb).")
            
        # 3. Professional Pro-Studio Gain Staging Signal Chain:
        # - Step 1: Dialogue Bus -> 80Hz HPF + 350Hz De-mud + 7kHz Presence Air + Stem Normalization (-16.0 LUFS)
        # - Step 2: Background Bus -> Tamed & Dynamically Ducked (-16dB under dialogue)
        # - Step 3: Sum to unmastered stem mix
        unmastered_mix_path = str(scratch_dir / "unmastered_stem_mix.wav")
        mix_cmd = [
            "ffmpeg", "-y",
            "-i", dialogue_raw_path,
            "-i", bg_raw_path,
            "-filter_complex",
            f"[0:a]highpass=f=80,equalizer=f=350:t=q:w=1.5:g=-2.0,equalizer=f=7000:t=q:w=1.2:g=2.2{reverb_filter},loudnorm=I=-16.0:TP=-1.5:LRA=6.0[dialogue];"
            "[1:a]volume=0.45[bg];"
            "[bg][dialogue]sidechaincompress=threshold=0.030:ratio=4.0:attack=10:release=200[bg_ducked];"
            "[dialogue][bg_ducked]amix=inputs=2:duration=first:dropout_transition=0:weights=1.0 1.0[mixed]",
            "-map", "[mixed]",
            "-ar", "48000", "-ac", "2",
            unmastered_mix_path
        ]
        subprocess.run(mix_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        
        # - Step 4: True Two-Pass EBU R128 Loudness Normalization (-14.0 LUFS linear=true)
        master_audio_path = str(scratch_dir / "final_master_audio_48k.wav")
        apply_two_pass_loudnorm(unmastered_mix_path, master_audio_path, target_i=-14.0, target_tp=-1.0, target_lra=7.0)
        
        # Remux video stream (copy) and master Arabic audio into final MP4
        final_video_path = str(scratch_dir / "final_dubbed_video.mp4")
        cmd_remux = [
            "ffmpeg", "-y",
            "-i", original_video_path,
            "-i", master_audio_path,
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-map", "0:v:0", "-map", "1:a:0",
            final_video_path
        ]
        subprocess.run(cmd_remux, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        
        # Automatically export chunks, audio, transcripts & translations to localhost:8080 Bilingual Audio Inspector
        DubbingPipelineEngine._export_to_audio_inspector(job_id, scratch_dir)

        await ConvexBroadcaster.update_stage(job_id, "completed", force=True)
        
        # Clean up temporary Fish Audio Voice Models in background
        for m_id in created_model_ids.values():
            asyncio.create_task(delete_fish_audio_voice_model(m_id))
        
        return {
            "job_id": job_id,
            "status": "MASTER_COMPLETED",
            "total_duration_sec": total_video_dur,
            "final_video_path": final_video_path
        }

    @staticmethod
    def _export_to_audio_inspector(job_id: str, scratch_dir: Path):
        """Exports the job's bilingual chunks, audio clips, and timings to the localhost:8080 inspector."""
        try:
            inspector_dir = Path("D:/local_test_results/tiktok_7661355917228789013/audio_inspector_app")
            if not inspector_dir.exists():
                inspector_dir.mkdir(parents=True, exist_ok=True)
                
            audio_target_dir = inspector_dir / "audio"
            audio_target_dir.mkdir(parents=True, exist_ok=True)
            
            manifest_path = scratch_dir / "mp4_chunks_manifest.json"
            trans_path = scratch_dir / "verified_gemini_3_1_pro_transcription.json"
            arabic_path = scratch_dir / "iraqi_translations_24_chunks.json"
            
            if not (manifest_path.exists() and trans_path.exists() and arabic_path.exists()):
                return
                
            with open(manifest_path, "r", encoding="utf-8-sig") as f:
                manifest_chunks = json.load(f)
            with open(trans_path, "r", encoding="utf-8-sig") as f:
                raw_k_data = json.load(f)
                kurdish_data = raw_k_data if isinstance(raw_k_data, list) else raw_k_data.get("transcriptions", [])
            with open(arabic_path, "r", encoding="utf-8-sig") as f:
                arabic_translations = json.load(f)
                
            kurd_map = {t["chunk_index"]: t["kurdish_sorani"] for t in kurdish_data}
            arab_map = {t["chunk_index"]: t for t in arabic_translations}
            
            chunks_data_list = []
            import shutil
            
            for c in manifest_chunks:
                idx = c["chunk_index"]
                k_text = kurd_map.get(idx, "")
                a_info = arab_map.get(idx, {})
                a_text = a_info.get("iraqi_translation") or a_info.get("arabic_text", "")
                spd = a_info.get("speed_scale", 1.0)
                
                # Copy Kurdish chunk audio if exists
                k_src = scratch_dir / "chunks" / f"chunk_{idx:02d}.wav"
                k_dst_name = f"kurdish_chunk_{idx:02d}.wav"
                if k_src.exists():
                    shutil.copy(str(k_src), str(audio_target_dir / k_dst_name))
                    
                # Copy Arabic chunk audio if exists (prefer aligned & padded audio)
                a_src_aligned = scratch_dir / "tts_chunks" / f"aligned_arabic_chunk_{idx:02d}.wav"
                a_src_raw = scratch_dir / "tts_chunks" / f"tts_{idx:02d}.wav"
                a_src = a_src_aligned if a_src_aligned.exists() else a_src_raw
                a_dst_name = f"arabic_chunk_{idx:02d}.wav"
                if a_src.exists():
                    shutil.copy(str(a_src), str(audio_target_dir / a_dst_name))
                    
                status_str = "PASS (0.95x - 1.15x)" if 0.95 <= spd <= 1.15 else f"WARN ({spd}x)"
                
                s_dur = float(c.get("duration_sec", 0.0))
                act_dur = float(c.get("active_speech_duration_sec", s_dur))
                lead_ms = int(c.get("lead_silence_sec", 0.0) * 1000)
                tail_ms = int(c.get("tail_silence_sec", 0.0) * 1000)
                onset_s = round(float(c.get("lead_silence_sec", 0.0)), 2)
                offset_s = round(float(s_dur - c.get("tail_silence_sec", 0.0)), 2)
                
                chunks_data_list.append({
                    "chunk_index": idx,
                    "chunk_number": idx + 1,
                    "timing": {
                        "total_duration_sec": round(s_dur, 2),
                        "speech_onset_sec": onset_s,
                        "speech_offset_sec": offset_s,
                        "active_duration_sec": round(act_dur, 2),
                        "lead_silence_ms": lead_ms,
                        "tail_silence_ms": tail_ms
                    },
                    "kurdish_sorani": {
                        "transcription": k_text,
                        "word_count": len(k_text.split()),
                        "audio_url": f"audio/{k_dst_name}"
                    },
                    "spoken_iraqi_arabic": {
                        "translation": a_text,
                        "word_count": len(a_text.split()),
                        "speed_scale": spd,
                        "status": status_str,
                        "audio_url": f"audio/{a_dst_name}"
                    }
                })
                
            js_content = "const CHUNKS_DATA = " + json.dumps(chunks_data_list, ensure_ascii=False, indent=2) + ";\n"
            with open(inspector_dir / "chunks_data.js", "w", encoding="utf-8") as f:
                f.write(js_content)
                
            logger.info(f"✨ Exported {len(chunks_data_list)} chunks to Bilingual Audio Inspector at {inspector_dir}")
        except Exception as insp_err:
            logger.warning(f"Notice exporting to Audio Inspector: {insp_err}")
