"""8.2 Planner invariants: asserts, not repairs.

A failure here is a planner bug; the session stops with PlannerError.
"""

from __future__ import annotations

import itertools

from edl_agent.planner._common import FPS, PlannerError


def assert_invariants(
    clips: list[dict],
    slots: list[dict],
    candidates_by_id: dict,
    sources_by_src: dict,
) -> None:
    """Assert planner invariants P1-P9 (#8.2) over the assembled clips.

    Raises:
        PlannerError: If any of P1-P9 is violated; the message identifies
            which invariant and, where applicable, which slot.
    """
    n_slots = len(slots)

    # P1
    if len(clips) != n_slots or [c["slot"] for c in clips] != [
        s["slot"] for s in slots
    ]:
        msg = "P1: clips do not cover the slots 1:1 in order"
        raise PlannerError(msg)

    # P2
    if len({c["candidate_id"] for c in clips}) != len(clips):
        msg = "P2: repeated candidate_id across clips"
        raise PlannerError(msg)

    for c in clips:
        if c["type"] != "image":
            # P3
            window = candidates_by_id[c["candidate_id"]]["window"]
            if not (window[0] - 1e-6 <= c["in_s"] and c["out_s"] <= window[1] + 1e-6):
                msg = f"P3: in_s/out_s outside window in slot {c['slot']}"
                raise PlannerError(msg)
            # P4
            duration_s = sources_by_src[c["src"]]["duration_s"]
            if not (0 <= c["in_s"] < c["out_s"] <= duration_s + 1e-6):
                msg = f"P4: invalid in_s/out_s in slot {c['slot']}"
                raise PlannerError(msg)
            # P5 (a ramp consumes `ramp_frames/FPS*ramp_speed` source seconds
            # for its `ramp_frames` output frames; the rest is 1.0x)
            src_s = c["out_s"] - c["in_s"]
            n_ramp = 0
            if c["effect"] == "ramp":
                p = c["effect_params"]
                n_ramp = p["ramp_frames"]
                src_s -= n_ramp / FPS * p["ramp_speed"]
            expected_n_frames = round(src_s / c["speed"] * FPS) + n_ramp
            if expected_n_frames != c["n_frames"]:
                msg = f"P5: n_frames mismatch in slot {c['slot']}"
                raise PlannerError(msg)

        # P8
        crop = c["crop"]
        if not (
            0 <= crop["x"] <= 1
            and 0 <= crop["y"] <= 1
            and 0 < crop["w"] <= 1
            and 0 < crop["h"] <= 1
        ):
            msg = f"P8: crop outside [0,1] in slot {c['slot']}"
            raise PlannerError(msg)
        px = c["crop_px"]
        if not (
            px["x"] >= 0
            and px["x"] + px["w"] <= c["src_w"]
            and px["y"] >= 0
            and px["y"] + px["h"] <= c["src_h"]
        ):
            msg = f"P8: crop_px outside W x H in slot {c['slot']}"
            raise PlannerError(msg)
        if px["w"] % 2 != 0 or px["h"] % 2 != 0:
            msg = f"P8: odd crop_px in slot {c['slot']}"
            raise PlannerError(msg)
        if c["layout"] == "crop" and abs(px["w"] / px["h"] - 9 / 16) * px["h"] > 2:
            msg = f"P8: crop_px does not respect 9:16 in slot {c['slot']}"
            raise PlannerError(msg)

        # P9: every clip holds at least 30 frames.
        if c["n_frames"] < 30:
            msg = f"P9: n_frames < 30 in slot {c['slot']}"
            raise PlannerError(msg)

    # P6
    if clips[0]["timeline_start_f"] != 0:
        msg = "P6: timeline_start_f[0] != 0"
        raise PlannerError(msg)
    if clips[-1]["timeline_end_f"] != slots[-1]["end_f"]:
        msg = "P6: timeline_end_f[-1] != duration_f"
        raise PlannerError(msg)
    for a, b in itertools.pairwise(clips):
        if a["timeline_end_f"] != b["timeline_start_f"]:
            msg = f"P6: gap in the timeline between slots {a['slot']} and {b['slot']}"
            raise PlannerError(msg)
    if sum(c["n_frames"] for c in clips) != slots[-1]["end_f"]:
        msg = "P6: sum(n_frames) != duration_f"
        raise PlannerError(msg)

    # P7: no overlaps of the same source (0.25s margin)
    by_src: dict[str, list[dict]] = {}
    for c in clips:
        if c["type"] != "image":
            by_src.setdefault(c["src"], []).append(c)
    for segs in by_src.values():
        ordered = sorted(segs, key=lambda c: c["in_s"])
        for a, b in itertools.pairwise(ordered):
            if a["out_s"] + 0.25 > b["in_s"] + 1e-6:
                msg = f"P7: overlap of the same source {a['src']}"
                raise PlannerError(msg)
