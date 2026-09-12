"""Layer 2 - Candidates (candidates.json), #4.3.

Consumes the per-source feature series produced by `features.py` (one series
per video source) and produces the `peak`/`calm`/`image` candidates that the
planner and the LLM selector consume.
"""

from __future__ import annotations

from ._common import FPS, edge_margin_s
from .build import build_image_candidate, build_video_candidates
from .calm import find_calm_windows
from .frames import build_contact_sheet, extract_peak_frames
from .peaks import find_peak_windows
from .scoring import admits_slots, score_cv

__all__ = [
    "FPS",
    "admits_slots",
    "build_contact_sheet",
    "build_image_candidate",
    "build_video_candidates",
    "edge_margin_s",
    "extract_peak_frames",
    "find_calm_windows",
    "find_peak_windows",
    "score_cv",
]
