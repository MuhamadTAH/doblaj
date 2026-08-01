import os
import json
import logging
import wave
from pathlib import Path

logger = logging.getLogger(__name__)

def run_translation_pacing_calibration(session_ids: list):
    chunks_data = []
    
    for session_id in session_ids:
        state_path = Path("data/jobs/sessions") / str(session_id) / "state.json"
        if not state_path.exists():
            continue
            
        with open(state_path, "r", encoding="utf-8") as f:
            state = json.load(f)
            
        for chunk in state.get("chunks", []):
            chunk_id = chunk.get("chunk_id")
            kurdish_text = chunk.get("kurdish_raw", "")
            arabic_text = chunk.get("arabic_text", "")
            duration = chunk.get("speech_duration", chunk.get("duration_sec", 0.0))
            
            if not kurdish_text or not arabic_text or duration <= 0:
                continue
                
            raw_wav = Path("data/jobs/sessions") / str(session_id) / "tts" / f"raw_tts_{chunk_id}.wav"
            tts_duration = 0.0
            if raw_wav.exists():
                try:
                    from pydub import AudioSegment
                    audio = AudioSegment.from_file(str(raw_wav))
                    tts_duration = len(audio) / 1000.0
                except Exception:
                    pass
                    
            if tts_duration == 0.0:
                tts_duration = duration # Fallback if audio doesn't exist
                
            correction_time = tts_duration - duration
                
            k_words = len(kurdish_text.split())
            a_words = len(arabic_text.split())
            
            k_wps = k_words / duration
            a_wps = a_words / tts_duration
            word_ratio = a_words / k_words if k_words > 0 else 0
            
            speed_mult = k_wps / 1.90
            
            if speed_mult <= 0.85:
                pace_group = "Slow / Deliberate"
            elif 0.85 < speed_mult < 1.15:
                pace_group = "Normal"
            else:
                pace_group = "Machine-Gun (Fast)"
                
            scale_ratio = tts_duration / duration if duration > 0 else 1.0
            ideal_a_words = round(a_words * (1.0 / scale_ratio)) if scale_ratio > 0 else a_words
            ideal_word_ratio = ideal_a_words / k_words if k_words > 0 else 0
            
            chunks_data.append({
                "chunk_id": chunk_id,
                "duration": duration,
                "tts_duration": tts_duration,
                "correction_time": correction_time,
                "kurdish_words": k_words,
                "arabic_words": a_words,
                "kurdish_wps": k_wps,
                "arabic_wps": a_wps,
                "word_ratio": word_ratio,
                "scale_ratio": scale_ratio,
                "ideal_arabic_words": ideal_a_words,
                "ideal_word_ratio": ideal_word_ratio,
                "pace_group": pace_group
            })
            
    # Calculate Macro Averages using PERFECTED Ideal Ratios (excluding extreme outliers <= 2 words)
    valid_chunks = [c for c in chunks_data if c["kurdish_words"] > 2]
    
    slow_ratios = [c["ideal_word_ratio"] for c in valid_chunks if c["pace_group"] == "Slow / Deliberate"]
    normal_ratios = [c["ideal_word_ratio"] for c in valid_chunks if c["pace_group"] == "Normal"]
    fast_ratios = [c["ideal_word_ratio"] for c in valid_chunks if c["pace_group"] == "Machine-Gun (Fast)"]
    
    avg_slow = sum(slow_ratios) / len(slow_ratios) if slow_ratios else 0
    avg_normal = sum(normal_ratios) / len(normal_ratios) if normal_ratios else 0
    avg_fast = sum(fast_ratios) / len(fast_ratios) if fast_ratios else 0
    
    # Calculate Average Kurdish WPS per group
    slow_wps = [c["kurdish_wps"] for c in valid_chunks if c["pace_group"] == "Slow / Deliberate"]
    normal_wps = [c["kurdish_wps"] for c in valid_chunks if c["pace_group"] == "Normal"]
    fast_wps = [c["kurdish_wps"] for c in valid_chunks if c["pace_group"] == "Machine-Gun (Fast)"]
    
    avg_slow_wps = sum(slow_wps) / len(slow_wps) if slow_wps else 0
    avg_normal_wps = sum(normal_wps) / len(normal_wps) if normal_wps else 0
    avg_fast_wps = sum(fast_wps) / len(fast_wps) if fast_wps else 0
    
    # Scale Ratio Violations
    violators_fast = [c for c in chunks_data if c["scale_ratio"] < 0.95]
    violators_slow = [c for c in chunks_data if c["scale_ratio"] > 1.20]
    
    # Pird: was hardcoded to a developer's local antigravity brain dir with a
    # UUID fingerprint. See pass-7 review. Now respects CALIBRATION_OUT env
    # var, defaults to data/reports/ inside the project.
    out_file = os.getenv(
        "CALIBRATION_OUT",
        str(Path("data/reports/translation_pacing_calibration.md")),
    )
    Path(out_file).parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        f.write("## Translation Pacing Calibration Results\n")
        f.write(f"**Total Chunks Analyzed:** {len(chunks_data)}\n")
        f.write("\n### Scale Ratio Violations (FFmpeg limits)\n")
        f.write(f"- **Too Fast (Scale < 0.95):** {len(violators_fast)} chunks\n")
        f.write(f"- **Too Slow (Scale > 1.20):** {len(violators_slow)} chunks\n")
        f.write("\n### PERFECTED Macro-Averages (Corrected for Speed Violations)\n")
        f.write(f"- **Slow Group Baseline:** {avg_slow:.2f} (A:K Word Ratio) | Average Speaking Speed: {avg_slow_wps:.2f} WPS\n")
        f.write(f"- **Normal Group Baseline:** {avg_normal:.2f} (A:K Word Ratio) | Average Speaking Speed: {avg_normal_wps:.2f} WPS\n")
        f.write(f"- **Fast Group Baseline:** {avg_fast:.2f} (A:K Word Ratio) | Average Speaking Speed: {avg_fast_wps:.2f} WPS\n")
        
        f.write("\n### Data Table\n")
        f.write("| Chunk ID | Target Slot (s) | TTS Audio (s) | Scale Ratio | Violation | Kurd. Words | Arab. Words | Old Ratio | Ideal Arab. Words | Ideal Ratio | Spd Mult (vs Normal) | Speaker Pace Group |\n")
        f.write("|----------|-----------------|---------------|-------------|-----------|-------------|-------------|-----------|-------------------|-------------|----------------------|--------------------|\n")
        for idx, c in enumerate(chunks_data, start=1):
            scale_ratio = c['scale_ratio']
            violation_str = "-"
            if scale_ratio < 0.95:
                violation_str = f"{scale_ratio - 0.95:.2f}"
            elif scale_ratio > 1.20:
                violation_str = f"+{scale_ratio - 1.20:.2f}"
                
            speed_mult = c['kurdish_wps'] / avg_normal_wps if avg_normal_wps > 0 else 1.0
                
            f.write(f"| {idx} | {c['duration']:.2f} | {c['tts_duration']:.2f} | {scale_ratio:.2f} | {violation_str} | {c['kurdish_words']} | {c['arabic_words']} | {c['word_ratio']:.2f} | **{c['ideal_arabic_words']}** | {c['ideal_word_ratio']:.2f} | {speed_mult:.2f}x | {c['pace_group']} |\n")
        
if __name__ == '__main__':
    run_translation_pacing_calibration([5, 15])
