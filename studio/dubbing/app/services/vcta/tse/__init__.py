"""
Localized Target Speaker Extraction (TSE) Pipeline Package.
"""

from app.services.vcta.tse.pure_anchors import find_pure_anchors
from app.services.vcta.tse.processor import LocalTSEProcessor
from app.services.vcta.tse.overlap_resolver import resolve_overlap_dual_pass
from app.services.vcta.tse.quality_sieve import QualityVerificationSieve
from app.services.vcta.tse.master_assembler import MasterCanvasAssembler
from app.services.vcta.tse.tail_padded_processor import (
    process_with_forward_tail_padding,
    process_with_tail_padding
)
from app.services.vcta.tse.envelope_tracker import (
    RMSEnvelopeTracker,
    track_volume_envelope,
    VolumeEnvelopeProfile
)
from app.services.vcta.tse.windowed_tse import (
    DynamicAnchorManager,
    DynamicAnchorManager16k,
    process_sliding_window_ola_tse,
    process_sliding_window_ola_tse_unirate,
    process_truncated_sliding_window_ola_tse
)
from app.services.vcta.tse.tts_assembler import (
    TTSCanvasAssembler,
    assemble_and_mimic_tts_fade
)

__all__ = [
    "find_pure_anchors",
    "LocalTSEProcessor",
    "resolve_overlap_dual_pass",
    "QualityVerificationSieve",
    "MasterCanvasAssembler",
    "process_with_forward_tail_padding",
    "process_with_tail_padding",
    "RMSEnvelopeTracker",
    "track_volume_envelope",
    "VolumeEnvelopeProfile",
    "DynamicAnchorManager",
    "DynamicAnchorManager16k",
    "process_sliding_window_ola_tse",
    "process_sliding_window_ola_tse_unirate",
    "process_truncated_sliding_window_ola_tse",
    "TTSCanvasAssembler",
    "assemble_and_mimic_tts_fade"
]
