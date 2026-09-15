"""6.3 In/out computation (peak on beat)."""

from __future__ import annotations

from edl_agent.planner._common import FPS


def compute_in_out(
    candidate: dict, slot: dict, role: str, ramp: dict | None, config: dict
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
        ramp: `{"speed": s, "frames": n}` to slow a `"peak"` candidate to
            `s` for `n` output frames centred on the beat (hook only, see
            `_common.hook_ramp`), or `None` for flat 1.0x. Ignored unless
            `kind == "peak"` and the slot has >= 2 beats.
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
        - `ramp` (dict | None): `{"speed", "frames", "start_f"}` when a
          ramp applies (`frames` is clamped to the slot, `start_f` is the
          first slowed output frame); `None` otherwise.
        - `peak_f` (int | None): output frame index of the peak beat
          (`= lead_f`); `None` for `kind == "image"`.
    """
    d_f = slot["end_f"] - slot["start_f"]
    warnings: list[str] = []

    if candidate["kind"] == "image":
        return {
            "in_s": 0.0,
            "out_s": d_f / FPS,
            "n_frames": d_f,
            "timeline_start_f": slot["start_f"],
            "timeline_end_f": slot["end_f"],
            "warnings": warnings,
            "ramp": None,
            "peak_f": None,
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

    # ponytail: hard-step ramp (1.0 -> s -> 1.0); add easing in setpts if abrupt.
    ramp_out = None
    need_s = d_f / FPS
    lead_src_s = lead_f / FPS
    if ramp is not None and candidate["kind"] == "peak" and len(beats) >= 2:
        s, n = ramp["speed"], ramp["frames"]
        a = max(0, lead_f - n // 2)
        b = min(d_f, a + n)
        n_eff = b - a
        need_s = (d_f - n_eff) / FPS + n_eff / FPS * s
        lead_src_s = a / FPS + (lead_f - a) / FPS * s
        ramp_out = {"speed": s, "frames": n_eff, "start_f": a}

    t_peak = candidate["t_peak"]
    raw_in_s = t_peak - lead_src_s
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
        "ramp": ramp_out,
        "peak_f": lead_f,
    }
