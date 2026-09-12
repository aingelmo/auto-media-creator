"""Layer 4 - Deterministic planner (snapper).

See docs/architecture/arquitectura_edl_agent_v4.md #6. The LLM decides
*what* (candidates, role, rank, exercise); this module decides *when* and
*where*: exact frames, beat alignment, develop ordering, pixel-space crop.
"""

from __future__ import annotations

from ._common import DEFAULT_CONFIG, FPS, PlannerError, admits
from .assignment import (
    Assignment,
    arc_order,
    assign_slots,
    place_develop_arc,
    select_develop,
)
from .crop import compute_crop
from .effects import effect_for
from .pipeline import build_clips
from .timing import compute_in_out

__all__ = [
    "DEFAULT_CONFIG",
    "FPS",
    "Assignment",
    "PlannerError",
    "admits",
    "arc_order",
    "assign_slots",
    "build_clips",
    "compute_crop",
    "compute_in_out",
    "effect_for",
    "place_develop_arc",
    "select_develop",
]
