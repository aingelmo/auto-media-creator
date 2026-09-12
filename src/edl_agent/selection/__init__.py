"""Layer 5 - S-checks (#8.1) and rules fallback (#8.6).

Reconciles a `selection.json` (LLM output) against `candidates.json` and
fills, role by role, any gaps with the 0-EUR rules fallback. Produces the
`selected` list consumed by `planner.assign_slots`. If there is no LLM
selection (``selection is None``), the entire result comes from the
fallback.
"""

from __future__ import annotations

from edl_agent.selection.pipeline import build_selected
from edl_agent.selection.s_checks import apply_s_checks

__all__ = [
    "apply_s_checks",
    "build_selected",
]
