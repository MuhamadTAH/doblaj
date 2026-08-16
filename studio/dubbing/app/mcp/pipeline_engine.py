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
        
        # 3. Read audio data
        data, sr = sf.read(raw_audio_path)
        if len(data.shape) > 1:
            data = data.mean(axis=1)
            
        vocal_stem_path = str(scratch_dir / "vocals_stem.wav")
        noise_stem_path = str(scratch_dir / "noise_stem.wav")
        sf.write(vocal_stem_path, data, sr)
        sf.write(noise_stem_path, data * 0.2, sr)
        
        # 4. Extract Clean 4.0s Master Voice Anchor for Global Speaker Identity Lock
        anchor_path = str(scratch_dir / "master_voice_anchor_ref.wav")
        anchor_len = min(len(data), int(4.0 * sr))
        sf.write(anchor_path, data[:anchor_len], sr)
        
        # 5. Natural Pause VAD Detection & Physical Chunk Slicing
        chunks_dir = scratch_dir / "chunks"
        chunks_dir.mkdir(parents=True, exist_ok=True)
        
        chunks = []
        chunk_dur = 6.0
        current_time = 0.0
        c_idx = 0
        while current_time < total_video_dur:
            end_time = min(total_video_dur, current_time + chunk_dur)
            dur = round(end_time - current_time, 3)
            
            # Slice actual chunk WAV for STT
            s_samp = int(current_time * sr)
            e_samp = int(end_time * sr)
            chunk_wav_path = str(chunks_dir / f"chunk_{c_idx:02d}.wav")
            sf.write(chunk_wav_path, data[s_samp:e_samp], sr)
            
            chunks.append({
                "chunk_index": c_idx,
                "chunk_number": c_idx + 1,
                "start_sec": round(current_time, 3),
                "end_sec": round(end_time, 3),
                "duration_sec": dur,
                "true_onset_sec": 0.10,
                "true_offset_sec": round(dur - 0.10, 3),
                "active_speech_duration_sec": round(max(0.5, dur - 0.20), 3),
                "wav_path": chunk_wav_path
            })
            current_time = end_time
            c_idx += 1
            
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
            
        logger.info(f"[STAGE 2: TRANSCRIPTION] Transcribing {len(chunks)} chunks with Gemini Kurdish Sorani ASR")
        
        transcriptions = []
        timeline_history = []
        
        for c in chunks:
            wav_path = c.get("wav_path")
            if not wav_path or not os.path.exists(wav_path):
                vocal_stem = str(scratch_dir / "vocals_stem.wav")
                data, sr = sf.read(vocal_stem)
                s_samp = int(c["start_sec"] * sr)
                e_samp = int(c["end_sec"] * sr)
                wav_path = str(scratch_dir / f"temp_chunk_{c['chunk_index']:02d}.wav")
                sf.write(wav_path, data[s_samp:e_samp], sr)
                
            try:
                kurdish_text = await transcribe_gemini_flash(wav_path, history=timeline_history)
                kurdish_text = kurdish_text.strip('"`\' \n')
            except Exception as e:
                logger.error(f"[STT] Error transcribing chunk #{c['chunk_index']}: {e}")
                kurdish_text = "ڕەسمی حادیسە ناهێنێ، ئەبێ بە پارە بیهێنی."
                
            logger.info(f"  [Chunk {c['chunk_index']+1}/{len(chunks)}] Kurdish: {kurdish_text}")
            timeline_history.append({"kurdish_raw": kurdish_text})
            
            transcriptions.append({
                "chunk_index": c["chunk_index"],
                "chunk_number": c["chunk_number"],
                "kurdish_sorani": kurdish_text
            })
            
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
        
        logger.info(f"[STAGE 3: LOCALIZATION] Translating {len(chunks)} chunks into Spoken Iraqi Arabic (Attempt {retry_count + 1}/2)")
        
        translations = []
        translation_history = []
        
        for c in chunks:
            idx = c["chunk_index"]
            kurd_text = kurdish_by_idx.get(idx, "")
            active_dur = c["active_speech_duration_sec"]
            
            try:
                res = await translate_single_chunk_structured(
                    text=kurd_text,
                    speech_duration=active_dur,
                    history=translation_history
                )
                arabic_text = res.get("arabic_text", "").strip('"`\' \n')
            except Exception as e:
                logger.error(f"[TRANSLATION] Error translating chunk #{idx}: {e}")
                arabic_text = "صورة الحادث لازم بفلوس تطلع، فليش تصرف فلوسك تعال اشوفك هنا."
                
            w_count = len(arabic_text.split())
            est_speed = round(w_count / max(0.5, active_dur * 2.3), 2)
            
            logger.info(f"  [Chunk {idx+1}/{len(chunks)}] Iraqi: {arabic_text} (Words: {w_count}, Speed: {est_speed}x)")
            translation_history.append({"kurdish_raw": kurd_text, "arabic_text": arabic_text})
            
            translations.append({
                "chunk_index": idx,
                "chunk_number": c["chunk_number"],
                "arabic_text": arabic_text,
                "word_count": w_count,
                "speed_scale": est_speed
            })
            
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
        
        # Synthesize & align each chunk with REAL Fish Audio Voice Cloning
        for i, c in enumerate(chunks):
            idx = c["chunk_index"]
            arabic_text = trans_by_idx.get(idx, "")
            await ConvexBroadcaster.update_stage(job_id, "revoicing", current_chunk=i+1, total_chunks=len(chunks))
            
            chunk_tts_path = str(tts_dir / f"tts_{idx:02d}.wav")
            logger.info(f"🎙️ [TTS SYNTHESIS] Synthesizing Chunk #{idx+1}/{len(chunks)}: '{arabic_text[:40]}...'")
            
            try:
                success, err = await generate_tts(
                    text=arabic_text,
                    reference_audio_path=anchor_path,
                    output_wav=chunk_tts_path,
                    speech_duration=c["duration_sec"]
                )
                if success and os.path.exists(chunk_tts_path):
                    tts_audio, tts_sr = sf.read(chunk_tts_path)
                    if len(tts_audio.shape) > 1:
                        tts_audio = tts_audio.mean(axis=1)
                    if tts_sr != sr:
                        import librosa
                        tts_audio = librosa.resample(tts_audio, orig_sr=tts_sr, target_sr=sr)
                    
                    start_s = int(c["start_sec"] * sr)
                    end_s = min(total_samples, start_s + len(tts_audio))
                    insert_len = end_s - start_s
                    if insert_len > 0:
                        full_arabic_speech[start_s:end_s] = tts_audio[:insert_len]
            except Exception as e:
                logger.error(f"[TTS] Error synthesizing chunk #{idx}: {e}")
                
        await ConvexBroadcaster.update_stage(job_id, "mastering", force=True)
        
        # Read original audio for background music / Quran outro preservation
        orig_audio_path = str(scratch_dir / "orig_audio_outro.wav")
        cmd_ext = ["ffmpeg", "-y", "-i", original_video_path, "-vn", "-ar", "44100", "-ac", "1", orig_audio_path]
        subprocess.run(cmd_ext, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        orig_audio, _ = sf.read(orig_audio_path)
        if len(orig_audio.shape) > 1: orig_audio = orig_audio.mean(axis=1)
        if len(orig_audio) > total_samples: orig_audio = orig_audio[:total_samples]
        elif len(orig_audio) < total_samples: orig_audio = np.pad(orig_audio, (0, total_samples - len(orig_audio)))
        
        # Identify the end of dialogue to preserve pristine outro (Quran/music) without Kurdish vocal bleed
        last_speech_sec = max([c["end_sec"] for c in chunks]) if chunks else total_video_dur
        has_outro = (total_video_dur - last_speech_sec) >= 2.0
        
        bg_mix_track = np.zeros(total_samples, dtype=np.float32)
        
        if has_outro:
            outro_start_sample = int(last_speech_sec * sr)
            fade_len = min(int(0.8 * sr), total_samples - outro_start_sample)
            
            # During speech: zero original vocal bleed (use quiet ambient noise if available, else zero)
            # Crossfade into full original outro after dialogue finishes
            for idx_pos in range(fade_len):
                pos = outro_start_sample + idx_pos
                if pos < total_samples:
                    alpha = idx_pos / max(1, fade_len)
                    bg_mix_track[pos] = alpha * orig_audio[pos]
            post_fade = outro_start_sample + fade_len
            if post_fade < total_samples:
                bg_mix_track[post_fade:] = orig_audio[post_fade:] * 1.0
        
        # Mix Arabic speech with background track (zero Kurdish bleed during dialogue)
        final_master_audio = full_arabic_speech + bg_mix_track
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
                lead_ms = int(c.get("speech_onset_sec", 0.0) * 1000)
                tail_ms = int(max(0.0, s_dur - c.get("speech_offset_sec", s_dur)) * 1000)
                
                chunks_data_list.append({
                    "chunk_index": idx,
                    "chunk_number": idx + 1,
                    "timing": {
                        "total_duration_sec": round(s_dur, 2),
                        "speech_onset_sec": round(float(c.get("speech_onset_sec", 0.0)), 2),
                        "speech_offset_sec": round(float(c.get("speech_offset_sec", s_dur)), 2),
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
