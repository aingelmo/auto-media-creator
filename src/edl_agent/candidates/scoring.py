"""Slot admission and CV-only quality scoring, per #4.3."""

from __future__ import annotations

from edl_agent.candidates._common import FPS


def admits_slots(
    window: tuple[float, float], slots: list[dict], speed: float = 1.0, fps: int = FPS
) -> list[int]:
    """List the slots a candidate window can fill, per #4.3 `admits_slots`.

    Uses the same admission calculation as #6.1. Precomputed here so that
    candidates that fit no slot at all are never sent to the LLM selector.

    Args:
        window: `(start_s, end_s)` bounds of the candidate.
        slots: Slot definitions, as in `slots.json["slots"]`. Each dict
            needs at least `slot` (int, slot index) and `start_f`/`end_f`
            (int, timeline frame bounds).
        speed: Playback speed multiplier to be applied to this candidate
            (e.g. 0.5 for slow motion). Defaults to 1.0.
        fps: Target frame rate. Defaults to `FPS` (30).

    Returns:
        List of `slot` indices (from `slots`) whose duration fits within
        `window` at the given `speed`.
    """
    out = []
    for s in slots:
        d_f = s["end_f"] - s["start_f"]
        need_s = d_f / fps * speed
        if (window[1] - window[0]) >= need_s + 2 / fps:
            out.append(s["slot"])
    return out


def score_cv(kp_speed: float, sharpness: float, bbox: tuple | None, kind: str) -> float:
    """Compute the computer-vision-only quality score `score_cv`, per #4.3.

    Used by the rules fallback (#8.6) and by the planner's relaxation path
    when no LLM selection is available for a role.

    Args:
        kp_speed: Normalized action-keypoint speed at the candidate's peak
            (or representative sample), in [0, 1].
        sharpness: Normalized sharpness at the candidate's peak (or
            representative sample), in [0, 1].
        bbox: Subject bounding box `(x0, y0, x1, y1)`, normalized to [0, 1],
            or `None` if no subject was tracked (treated as centered).
        kind: Candidate kind, one of `"peak"`, `"calm"`, `"image"`. Action is
            rewarded for `"peak"` and penalized for `"calm"` (a calm shot
            scores higher the less action it has).

    Returns:
        Weighted score combining action term (0.5), sharpness (0.3), and
        subject centrality (0.2). Not bounded to a fixed range but
        comparable across candidates of the same run.
    """
    cx = (bbox[0] + bbox[2]) / 2 if bbox else 0.5
    centrality = 1 - 2 * abs(cx - 0.5)
    action_term = 0.5 * (1 - kp_speed) if kind == "calm" else 0.5 * kp_speed
    return action_term + 0.3 * sharpness + 0.2 * centrality
