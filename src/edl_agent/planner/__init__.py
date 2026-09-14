"""Layer 4 - Deterministic planner (snapper).

See docs/architecture/06-planner.md #6. The LLM decides
*what* (candidates, role, rank, exercise); this module decides *when* and
*where*: exact frames, beat alignment, develop ordering, pixel-space crop.
"""

from __future__ import annotations

from edl_agent.planner._common import DEFAULT_CONFIG, FPS, PlannerError, admits
from edl_agent.planner.assignment import (
    Assignment,
    arc_order,
    assign_slots,
    place_develop_arc,
    select_develop,
)
from edl_agent.planner.color import apply_color_match, color_fix_for, measure_clip_color
from edl_agent.planner.crop import compute_crop
from edl_agent.planner.effects import effect_for
from edl_agent.planner.pipeline import build_clips
from edl_agent.planner.timing import compute_in_out

__all__ = [
    "DEFAULT_CONFIG",
    "FPS",
    "Assignment",
    "PlannerError",
    "admits",
    "apply_color_match",
    "arc_order",
    "assign_slots",
    "build_clips",
    "color_fix_for",
    "compute_crop",
    "compute_in_out",
    "effect_for",
    "measure_clip_color",
    "place_develop_arc",
    "select_develop",
]
