"""6.3 In/out computation (peak on beat)."""

from __future__ import annotations

from edl_agent.planner._common import FPS


def compute_in_out(
    candidate: dict, slot: dict, role: str, speed: float, config: dict
) -> dict:
    """Align a candidate's peak to the slot's beat and return in/out timing, per #6.3.

    Args:
        candidate: Candidate dict (see `candidates.build_video_candidates`
            or `candidates.build_image_candidate`). Reads `kind`, `window`,
            `t_peak`.
        slot: Slot dict, with `start_f`, `end_f`, and optionally
            `beats_rel_f` (list[int], beat offsets relative to the slot
            start, in frames; defaults to `[0]` if absent).
        role: Slot role (`"hook"`, `"develop"`, `"close"`); a `"calm"`-kind
            candidate centers the clip on the slot instead of aligning to a
            beat. A `"close"` slot filled by a `"peak"`-kind fallback
            candidate keeps the peak near the slot start instead, so the
            clip mostly shows the subject settling after the action.
        speed: Playback speed multiplier.
        config: Planner config; reads `peak_beat_index` (which beat within
            the slot the peak aligns to, when there are >=2 beats).

    Returns:
        Dict with keys:
        - `in_s`, `out_s` (float): source in/out points, in seconds.
        - `n_frames` (int): slot duration, in frames (`= d_f`).
        - `timeline_start_f`, `timeline_end_f` (int): copied from `slot`.
        - `warnings` (list[str]): `["peak_off_beat"]` if the peak had to be
          shifted by more than 2 frames to fit inside the candidate's
          window; empty otherwise. Always empty for `kind == "image"`.
    """
    d_f = slot["end_f"] - slot["start_f"]
    need_s = d_f / FPS * speed
    warnings: list[str] = []

    if candidate["kind"] == "image":
        return {
            "in_s": 0.0,
            "out_s": d_f / FPS,
            "n_frames": d_f,
            "timeline_start_f": slot["start_f"],
            "timeline_end_f": slot["end_f"],
            "warnings": warnings,
        }

    window = tuple(candidate["window"])
    beats = slot.get("beats_rel_f", [0])
    if candidate["kind"] == "calm":
        lead_f = d_f // 2
    elif role == "close":
        # Fallback peak-kind close: keep the peak near the start so most of
        # the slot shows the subject settling afterwards, not building up.
        lead_f = round(0.15 * d_f)
    elif len(beats) >= 2:
        idx = min(config.get("peak_beat_index", 1), len(beats) - 1)
        lead_f = beats[idx]
    else:
        lead_f = round(0.35 * d_f)

    lead = lead_f / d_f
    t_peak = candidate["t_peak"]
    raw_in_s = t_peak - lead * need_s
    in_s = max(window[0], min(raw_in_s, window[1] - need_s))
    out_s = in_s + need_s

    if abs(in_s - raw_in_s) > 2 / FPS:
        warnings.append("peak_off_beat")

    return {
        "in_s": in_s,
        "out_s": out_s,
        "n_frames": d_f,
        "timeline_start_f": slot["start_f"],
        "timeline_end_f": slot["end_f"],
        "warnings": warnings,
    }
