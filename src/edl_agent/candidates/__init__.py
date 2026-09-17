"""Layer 2 - Candidates (candidates.json), #4.3.

Consumes the per-source feature series produced by `features.py` (one series
per video source) and produces the `peak`/`calm`/`image` candidates that the
planner and the LLM selector consume.
"""

from __future__ import annotations

from edl_agent.candidates._common import FPS, edge_margin_s
from edl_agent.candidates.build import (
    build_image_candidate,
    build_video_candidates,
    readmit_candidates,
)
from edl_agent.candidates.calm import find_calm_windows
from edl_agent.candidates.dedup import dedup_windows_by_phash, suppress_peak_windows
from edl_agent.candidates.frames import build_contact_sheet, extract_peak_frames
from edl_agent.candidates.peaks import find_peak_windows
from edl_agent.candidates.scoring import admits_slots, score_cv

__all__ = [
    "FPS",
    "admits_slots",
    "build_contact_sheet",
    "build_image_candidate",
    "build_video_candidates",
    "dedup_windows_by_phash",
    "edge_margin_s",
    "extract_peak_frames",
    "find_calm_windows",
    "find_peak_windows",
    "readmit_candidates",
    "score_cv",
    "suppress_peak_windows",
]
