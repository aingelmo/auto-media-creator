"""Shared constants/helpers for S-checks and rules fallback (#8.1, #8.6)."""

from __future__ import annotations

ROLES = ("hook", "develop", "close")

FALLBACK_HOOK_MOTION_BG_MAX = 0.4
FALLBACK_HOOK_SHARPNESS_MIN = 0.5


def _centrality(bbox: tuple) -> float:
    cx = (bbox[0] + bbox[2]) / 2
    return 1 - 2 * abs(cx - 0.5)


def _slot_indices(slots: list[dict], role: str) -> list[int]:
    return [s["slot"] for s in slots if s["role"] == role]


def _admits(cand: dict, slot_indices: list[int]) -> bool:
    return any(s in cand["admits_slots"] for s in slot_indices)
