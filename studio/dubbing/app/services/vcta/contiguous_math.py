import logging

logger = logging.getLogger(__name__)

def calculate_contiguous_timeline(vad_chunks: list[dict], total_duration: float) -> list[dict]:
    """
    Takes raw VAD boundaries and expands them to create a contiguous zero-gap timeline.
    Safeguards against negative gaps (overlapping speech).
    """
    contiguous_chunks = []
    num_chunks = len(vad_chunks)
    
    if num_chunks == 0:
        return []
        
    for i, chunk in enumerate(vad_chunks):
        # 1. Calculate Contiguous Start
        if i == 0:
            contig_start = max(0.0, chunk["start"] - 1.5)
        else:
            prev_chunk = vad_chunks[i - 1]
            gap_before = chunk["start"] - prev_chunk["end"]
            
            if gap_before < 0:
                # Overlapping speech detected. Do not pull backward.
                contig_start = chunk["start"]
            else:
                # Bisect the silence, but strictly cap padding at 1.5 seconds
                pad_before = min(1.5, gap_before / 2.0)
                contig_start = chunk["start"] - pad_before
                
        # 2. Calculate Contiguous End
        if i == num_chunks - 1:
            # Strictly cap end padding at 1.5 seconds so final chunk doesn't bloat
            pad_after = min(1.5, total_duration - chunk["end"])
            contig_end = chunk["end"] + pad_after
        else:
            next_chunk = vad_chunks[i + 1]
            gap_after = next_chunk["start"] - chunk["end"]
            
            if gap_after < 0:
                # Overlapping speech detected. Do not chop off current chunk.
                contig_end = chunk["end"]
            else:
                # Bisect the silence, strictly cap padding at 1.5 seconds
                pad_after = min(1.5, gap_after / 2.0)
                contig_end = chunk["end"] + pad_after
                
        contig_duration = contig_end - contig_start
        
        # We replace the start_time, end_time, and duration properties so the rest of the 
        # pipeline uses the new contiguous boundaries naturally.
        chunk_out = dict(chunk)
        chunk_out["vad_start"] = chunk["start"]
        chunk_out["vad_end"] = chunk["end"]
        
        chunk_out["start_time"] = contig_start
        chunk_out["end_time"] = contig_end
        chunk_out["speech_duration"] = contig_duration
        chunk_out["total_duration"] = contig_duration
        chunk_out["is_micro"] = contig_duration < 0.8
        
        # Make sure chunk has an ID
        if "chunk_id" not in chunk_out:
            import uuid
            chunk_out["chunk_id"] = uuid.uuid4().hex[:8]
            
        contiguous_chunks.append(chunk_out)
        
    logger.info(f"[TIMELINE] Partitioned {num_chunks} chunks onto a {total_duration}s contiguous canvas.")
    return contiguous_chunks
