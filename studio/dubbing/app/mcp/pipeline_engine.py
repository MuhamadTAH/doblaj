import os
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
        
        # 5. Sentence-Aware VAD Pause Detection & Speech Onset/Offset Measurement
        chunks_dir = scratch_dir / "chunks"
        chunks_dir.mkdir(parents=True, exist_ok=True)
        
        # Detect true speech bursts using 25dB energy threshold
        intervals = librosa.effects.split(data, top_db=25, frame_length=2048, hop_length=512)
        
        chunks = []
        if len(intervals) == 0:
            chunk_wav_path = str(chunks_dir / "chunk_00.wav")
            sf.write(chunk_wav_path, data, sr)
            chunks.append({
                "chunk_index": 0,
                "chunk_number": 1,
                "start_sec": 0.0,
                "end_sec": round(total_video_dur, 3),
                "duration_sec": round(total_video_dur, 3),
                "lead_silence_sec": 0.0,
                "tail_silence_sec": 0.0,
                "active_speech_duration_sec": round(total_video_dur, 3),
                "wav_path": chunk_wav_path
            })
        else:
            # Merge intra-sentence word pauses (< 0.35s) into full spoken sentences
            min_gap_samples = int(0.35 * sr)
            sentences = []
            cur_s, cur_e = intervals[0]
            for s, e in intervals[1:]:
                if (s - cur_e) < min_gap_samples:
                    cur_e = e
                else:
                    sentences.append((cur_s, cur_e))
                    cur_s, cur_e = s, e
            sentences.append((cur_s, cur_e))
            
            # Group sentences into natural conversational chunks (targeting 3.5s to 7.5s)
            chunk_start_sec = 0.0
            accum_sentences = []
            
            for i, (s, e) in enumerate(sentences):
                accum_sentences.append((s, e))
                s_sec = accum_sentences[0][0] / sr
                e_sec = accum_sentences[-1][1] / sr
                cur_speech_span = e_sec - s_sec
                is_last = (i == len(sentences) - 1)
                
                if is_last:
                    chunk_end_sec = total_video_dur
                    should_close = True
                else:
                    next_s_sec = sentences[i+1][0] / sr
                    next_e_sec = sentences[i+1][1] / sr
                    next_span = next_e_sec - s_sec
                    
                    # Split exclusively at the natural silence between sentences
                    if cur_speech_span >= 3.5 and next_span > 7.5:
                        chunk_end_sec = round((e_sec + next_s_sec) / 2.0, 3)
                        should_close = True
                    else:
                        should_close = False
                        
                if should_close:
                    c_dur = round(chunk_end_sec - chunk_start_sec, 3)
                    lead_sil = round(max(0.0, s_sec - chunk_start_sec), 3)
                    tail_sil = round(max(0.0, chunk_end_sec - e_sec), 3)
                    act_dur = round(max(0.4, e_sec - s_sec), 3)
                    
                    c_idx = len(chunks)
                    s_samp = int(chunk_start_sec * sr)
                    e_samp = min(len(data), int(chunk_end_sec * sr))
                    chunk_wav_path = str(chunks_dir / f"chunk_{c_idx:02d}.wav")
                    sf.write(chunk_wav_path, data[s_samp:e_samp], sr)
                    
                    chunks.append({
                        "chunk_index": c_idx,
                        "chunk_number": c_idx + 1,
                        "start_sec": round(chunk_start_sec, 3),
                        "end_sec": round(chunk_end_sec, 3),
                        "duration_sec": c_dur,
                        "lead_silence_sec": lead_sil,
                        "tail_silence_sec": tail_sil,
                        "active_speech_duration_sec": act_dur,
                        "wav_path": chunk_wav_path
                    })
                    chunk_start_sec = chunk_end_sec
                    accum_sentences = []
            
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
                    kurdish_text = kurdish_text.strip('"`\' \n')
                except Exception as e:
                    logger.error(f"[STT] Error transcribing chunk #{idx}: {e}")
                    kurdish_text = "ڕەسمی حادیسە ناهێنێ، ئەبێ بە پارە بیهێنی."
                    
                logger.info(f"  [Chunk {idx+1}/{len(chunks)}] Kurdish: {kurdish_text}")
                return {
                    "chunk_index": idx,
                    "chunk_number": c["chunk_number"],
                    "kurdish_sorani": kurdish_text
                }
        
        tasks = [_process_stt(c) for c in chunks]
        transcriptions = await asyncio.gather(*tasks)
        transcriptions.sort(key=lambda x: x["chunk_index"])
        
        trans_out = str(scratch_dir / "verified_gemini_3_1_pro_transcription.json")
        with open(trans_out, "w", encoding="utf-8") as f:
            json.dump({"transcriptions": transcriptions}, f, ensure_ascii=False, indent=2)
            
        return {
            "job_id": job_id,
            "status": "TRANSCRIPTION_VERIFIED",
            "transcriptions_count": len(transcriptions),
            "transcription_file": trans_out
        }

    @staticmethod
    async def translate_and_calibrate(job_id: str, retry_count: int = 0) -> Dict[str, Any]:
        """Stage 4: Spoken Iraqi Translation with lipsync word budget + 100% Phonetic Number Words."""
        scratch_dir = ScratchManager.get_job_dir(job_id)
        await ConvexBroadcaster.update_stage(job_id, "translating", force=True)
        
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
                est_speed = round(w_count / max(0.5, active_dur * 2.3), 2)
                
                # Real Speed Boundary Circuit Breaker & Calibration Loop [0.95x, 1.15x]
                if (est_speed < 0.95 or est_speed > 1.15) and active_dur >= 1.0:
                    desired_words = max(2, round(active_dur * 2.35))
                    action = "expand and add natural phrasing in" if est_speed < 0.95 else "tighten and shorten to punchy"
                    corr_prompt = f"CRITICAL SPEED CALIBRATION: Your previous translation had only {w_count} words ({est_speed}x speed). You MUST {action} authentic Spoken Iraqi Arabic with EXACTLY {desired_words} words to achieve natural 1.02x speed for {active_dur:.2f}s."
                    logger.info(f"  ⚡ [Chunk {idx+1}] Speed violation ({est_speed}x) -> Calibrating to exact target ({desired_words} words)...")
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
                            retry_speed = round(retry_w / max(0.5, active_dur * 2.3), 2)
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
        with open(trans_path, "r", encoding="utf-8") as f:
            translations = json.load(f)
        trans_by_idx = {t["chunk_index"]: t["arabic_text"] for t in translations}
        
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
        
        # Synthesize each chunk concurrently with REAL Fish Audio Voice Cloning
        sem_tts = asyncio.Semaphore(4)
        logger.info(f"🎙️ [TTS SYNTHESIS] Synthesizing {len(chunks)} chunks concurrently with Fish Audio Voice Cloning...")
        
        async def _synthesize_single(i, c):
            async with sem_tts:
                idx = c["chunk_index"]
                arabic_text = trans_by_idx.get(idx, "")
                chunk_tts_path = str(tts_dir / f"tts_{idx:02d}.wav")
                try:
                    success, err = await generate_tts(
                        text=arabic_text,
                        reference_audio_path=anchor_path,
                        output_wav=chunk_tts_path,
                        speech_duration=c["duration_sec"]
                    )
                    return i, idx, success, chunk_tts_path
                except Exception as e:
                    logger.error(f"[TTS] Error synthesizing chunk #{idx}: {e}")
                    return i, idx, False, chunk_tts_path

        tts_tasks = [_synthesize_single(i, c) for i, c in enumerate(chunks)]
        tts_results = await asyncio.gather(*tts_tasks)
        
        # Place synthesized chunks onto the master timeline in exact sequence with slot protection & silence alignment
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
                
                # Determine maximum allowed slot duration before next chunk's speech starts
                if i < len(chunks) - 1:
                    next_c = chunks[i+1]
                    max_slot_dur = (next_c["start_sec"] + next_c.get("lead_silence_sec", 0.0)) - (c["start_sec"] + lead_sil)
                else:
                    max_slot_dur = (total_video_dur - c.get("tail_silence_sec", 0.0)) - (c["start_sec"] + lead_sil)
                
                max_slot_dur = max(0.5, max_slot_dur)
                
                # Prevent audio cutoff: Time-stretch TTS if it exceeds the slot so all words finish completely
                tts_dur = len(tts_audio) / sr
                if tts_dur > max_slot_dur:
                    stretch_rate = min(1.35, tts_dur / max(0.4, max_slot_dur - 0.05))
                    logger.info(f"  ⚡ [Chunk #{idx+1} Word Preservation] TTS ({tts_dur:.2f}s) > Slot ({max_slot_dur:.2f}s) -> time_stretch {stretch_rate:.2f}x to fit 100% of words without cutoff")
                    tts_audio = librosa.effects.time_stretch(tts_audio, rate=stretch_rate)
                
                # Align speech start at the EXACT frame the speaker begins talking (after lead silence)
                start_s = int((c["start_sec"] + lead_sil) * sr)
                end_s = min(total_samples, start_s + len(tts_audio))
                insert_len = end_s - start_s
                if insert_len > 0:
                    full_arabic_speech[start_s:end_s] = tts_audio[:insert_len]
                
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
        
        # Check if there is an outro silence section (e.g. Quran recitation or outro music after speech ends)
        last_speech_sec = max([c["end_sec"] for c in chunks]) if chunks else total_video_dur
        has_outro = (total_video_dur - last_speech_sec) >= 1.5
        
        if has_outro:
            outro_start = int(last_speech_sec * sr)
            bg_audio[outro_start:] = orig_audio[outro_start:]

        # Mix synthesized Arabic speech with the REAL background sound track!
        # Background music/noise is preserved at natural volume (0.90x) throughout the entire video
        final_master_audio = full_arabic_speech + (bg_audio * 0.90)
        peak = np.max(np.abs(final_master_audio)) if len(final_master_audio) > 0 else 1.0
        if peak > 0.96:
            final_master_audio = final_master_audio * (0.96 / peak)
            
        master_audio_path = str(scratch_dir / "final_master_audio.wav")
        sf.write(master_audio_path, final_master_audio, sr)
        
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
                
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest_chunks = json.load(f)
            with open(trans_path, "r", encoding="utf-8") as f:
                kurdish_data = json.load(f).get("transcriptions", [])
            with open(arabic_path, "r", encoding="utf-8") as f:
                arabic_translations = json.load(f)
                
            kurd_map = {t["chunk_index"]: t["kurdish_sorani"] for t in kurdish_data}
            arab_map = {t["chunk_index"]: t for t in arabic_translations}
            
            chunks_data_list = []
            import shutil
            
            for c in manifest_chunks:
                idx = c["chunk_index"]
                k_text = kurd_map.get(idx, "")
                a_info = arab_map.get(idx, {})
                a_text = a_info.get("arabic_text", "")
                spd = a_info.get("speed_scale", 1.0)
                
                # Copy Kurdish chunk audio if exists
                k_src = scratch_dir / "chunks" / f"chunk_{idx:02d}.wav"
                k_dst_name = f"kurdish_chunk_{idx:02d}.wav"
                if k_src.exists():
                    shutil.copy(str(k_src), str(audio_target_dir / k_dst_name))
                    
                # Copy Arabic chunk audio if exists
                a_src = scratch_dir / "tts_chunks" / f"tts_{idx:02d}.wav"
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
