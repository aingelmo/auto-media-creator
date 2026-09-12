"""Layer 4 - Deterministic planner (snapper).

See docs/architecture/arquitectura_edl_agent_v4.md #6. The LLM decides
*what* (candidates, role, rank, exercise); this module decides *when* and
*where*: exact frames, beat alignment, develop ordering, pixel-space crop.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any

from .render import crop_to_px, is_916

FPS = 30


class PlannerError(RuntimeError):
    """A planner invariant was violated, or a role has no admissible candidate.

    See #0, #8.2.
    """


DEFAULT_CONFIG = {
    "hook_speed": 1.0,  # the only role where 0.5 is allowed (#6)
    "peak_beat_index": 1,  # #6.3: peak lands on the slot's 2nd beat by default
    "allow_blur_pad": True,  # #6.4
    "upscale_threshold": 1.3,
    "ken_burns": True,  # #6.6
    "zoom_per_frame": 0.0015,
    "zoom_max": 1.08,
    "blur_radius": 20,
    "blur_power": 2,
    "bg_brightness": -0.1,
    "adjacency_gap_s": 0.25,  # #6.2.3 anti-overlap margin for the same source
}


# --------------------------------------------------------------------------
# 6.1 Admitting a candidate into a slot
# --------------------------------------------------------------------------


def admits(window: tuple[float, float], d_f: int, speed: float) -> bool:
    """Check whether a window admits a clip of `d_f` frames at `speed`, per #6.1.

    Args:
        window: `(start_s, end_s)` bounds of the candidate window, in
            seconds.
        d_f: Slot duration, in frames.
        speed: Playback speed multiplier to apply.

    Returns:
        `True` if the window is long enough to hold `d_f` frames at
        `speed` (with a 2-frame safety margin), `False` otherwise.
    """
    need_s = d_f / FPS * speed
    return (window[1] - window[0]) >= need_s + 2 / FPS


# --------------------------------------------------------------------------
# 6.2 Assignment
# --------------------------------------------------------------------------


def _norm_exercise(exercise: str) -> str:
    return exercise.lower().strip()


def _select_single(
    selected: list[dict],
    role: str,
    kinds: set[str] | None,
    candidates_by_id: dict,
    d_f: int,
    speed: float,
) -> dict | None:
    pool = sorted(
        (
            s
            for s in selected
            if s["role"] == role
            and (kinds is None or candidates_by_id[s["candidate_id"]]["kind"] in kinds)
        ),
        key=lambda s: s["rank"],
    )
    for s in pool:
        cand = candidates_by_id[s["candidate_id"]]
        if admits(tuple(cand["window"]), d_f, speed):
            return s
    return None


def _overlaps_used(
    cand: dict, in_s: float, out_s: float, used: list[dict], gap_s: float
) -> bool:
    for u in used:
        if u["src"] != cand["src"]:
            continue
        if in_s < u["out_s"] + gap_s and u["in_s"] < out_s + gap_s:
            return True
    return False


def select_develop(
    selected: list[dict],
    candidates_by_id: dict,
    develop_slots: list[dict],
    used: list[dict],
    config: dict,
) -> list[dict]:
    """Pick the `selected` entries taken for develop slots, per #6.2.3.

    Walks the develop-role pool in rank order (r1 = best) and greedily
    takes entries that fit a remaining develop slot duration, don't repeat
    the exercise or source of the previously taken entry, and don't
    time-overlap anything already placed on the timeline (respecting
    `config["adjacency_gap_s"]`). The final temporal order of the taken
    entries is decided separately by `place_develop_arc` (#6.2.4).

    Args:
        selected: Candidate selections (LLM output reconciled with
            fallback, see `selection.build_selected`). Each entry has
            `candidate_id` (str), `role` (str), `rank` (int, 1 = best),
            `exercise` (str).
        candidates_by_id: Mapping `candidate_id -> candidate dict` (see
            `candidates.build_video_candidates` for the candidate shape).
        develop_slots: Slot dicts with `role == "develop"`, each with
            `start_f`/`end_f` (int, frame bounds).
        used: Timeline segments already claimed by other roles (hook so
            far), each a dict with `src` (str), `in_s`/`out_s` (float,
            seconds). Not mutated in place for entries added here; new
            entries are appended as develop candidates are taken.
        config: Planner config (see `DEFAULT_CONFIG`); reads
            `adjacency_gap_s` and whatever `compute_in_out` needs.

    Returns:
        Subset of `selected` (role `"develop"`) taken, in rank order —
        not yet placed into slot order (see `place_develop_arc` for that).
    """
    k = len(develop_slots)
    free_durations = [s["end_f"] - s["start_f"] for s in develop_slots]
    pool = sorted(
        (s for s in selected if s["role"] == "develop"),
        key=lambda s: s["rank"],
    )
    taken: list[dict] = []
    prev_exercise: str | None = None
    prev_src: str | None = None
    for s in pool:
        if len(taken) >= k:
            break
        cand = candidates_by_id[s["candidate_id"]]
        admissible_d_f = next(
            (d for d in free_durations if admits(tuple(cand["window"]), d, 1.0)), None
        )
        if admissible_d_f is None:
            continue
        if prev_exercise is not None and _norm_exercise(s["exercise"]) == prev_exercise:
            continue
        if prev_src is not None and cand["src"] == prev_src:
            continue
        timing = compute_in_out(
            cand,
            {"start_f": 0, "end_f": admissible_d_f, "beats_rel_f": [0]},
            role="develop",
            speed=1.0,
            config=config,
        )
        if _overlaps_used(
            cand, timing["in_s"], timing["out_s"], used, config["adjacency_gap_s"]
        ):
            continue
        taken.append(s)
        used.append(
            {"src": cand["src"], "in_s": timing["in_s"], "out_s": timing["out_s"]}
        )
        free_durations.remove(admissible_d_f)
        prev_exercise = _norm_exercise(s["exercise"])
        prev_src = cand["src"]
    return taken


def arc_order(k: int) -> list[int]:
    """Compute the develop rank-to-slot order, per #6.2.4.

    Builds a "narrative arc" order (rising action then falling) rather than
    strict rank order, so the best-ranked develop shots land roughly in the
    middle of the develop block.

    Args:
        k: Number of develop slots.

    Returns:
        For each develop slot s1..sk (0-indexed in the returned list), the
        1-indexed rank of the candidate to place there. E.g. for `k=4`:
        `[2, 4, 3, 1]`.
    """
    evens = list(range(2, k + 1, 2))
    odds = list(range(1, k + 1, 2))
    return evens + odds[::-1]


def _adjacency_violations(
    chain: list[dict | None], candidates_by_id: dict
) -> list[int]:
    """List indices i where `chain[i]` and `chain[i+1]` repeat exercise or source."""
    bad = []
    for i in range(len(chain) - 1):
        a, b = chain[i], chain[i + 1]
        if a is None or b is None:
            continue
        ca, cb = (
            candidates_by_id[a["candidate_id"]],
            candidates_by_id[b["candidate_id"]],
        )
        if (
            _norm_exercise(a["exercise"]) == _norm_exercise(b["exercise"])
            or ca["src"] == cb["src"]
        ):
            bad.append(i)
    return bad


def place_develop_arc(
    taken: list[dict],
    hook: dict | None,
    close: dict | None,
    candidates_by_id: dict,
) -> tuple[list[dict], bool]:
    """Place the `taken` develop entries into slot order, per #6.2.4.

    Starts from `arc_order(k)`, then repairs up to 3 times by swapping
    adjacent develop entries whenever two neighbors (including the hook
    before and the close after) repeat an exercise or source. If a
    violation can't be fixed by swapping develops (e.g. it's against hook
    or close), falls back to plain rank order.

    Args:
        taken: Develop entries selected by `select_develop`, already
            sorted by rank (rank 1 = best, at index 0).
        hook: The entry placed in the hook slot (or `None`), used only to
            check adjacency against the first develop slot.
        close: The entry placed in the close slot (or `None`), used only to
            check adjacency against the last develop slot.
        candidates_by_id: Mapping `candidate_id -> candidate dict`.

    Returns:
        `(placement, arc_fallback)`: `placement` is `taken` reordered for
        slots s1..sk; `arc_fallback` is `True` if no arc arrangement was
        found and `placement` is just `taken` in rank order (caller should
        add an `"arc_fallback"` warning in that case).
    """
    k = len(taken)
    if k == 0:
        return [], False
    by_rank = {
        i + 1: s for i, s in enumerate(taken)
    }  # taken is already sorted by rank
    order = arc_order(k)
    placement = [by_rank[r] for r in order]

    for _ in range(3):
        chain = [hook, *placement, close]
        violations = _adjacency_violations(chain, candidates_by_id)
        # +1 because chain includes hook at position 0
        dev_violations = [i for i in violations if 0 < i < len(chain) - 1]
        if not violations:
            return placement, False
        if not dev_violations:
            # violation only against hook/close: can't be fixed by
            # swapping develops
            break
        i = dev_violations[0]
        dev_i = i - 1  # index within `placement`
        if dev_i + 1 < len(placement):
            placement[dev_i], placement[dev_i + 1] = (
                placement[dev_i + 1],
                placement[dev_i],
            )

    chain = [hook, *placement, close]
    if _adjacency_violations(chain, candidates_by_id):
        return list(taken), True  # #6.2.4: rank order, warning: arc_fallback
    return placement, False


# --------------------------------------------------------------------------
# 6.2.5 Relaxation. Implemented in selection.build_selected: if hook/close
# have no admissible free candidate, one already assigned to develop is
# preempted (reclaimed) -- develop is more flexible (N slots, typically more
# candidates) -- and the resulting gap is refilled from the remaining
# fallback pool. Only covers develop -> hook/close; if develop itself falls
# short with nothing left to fill it, this module still raises
# PlannerError below.
# --------------------------------------------------------------------------


@dataclass
class Assignment:
    """Result of #6.2: one candidate per slot (hook/develop/close), plus warnings."""

    hook: dict
    develop: list[dict]  # in order s1..sk, one per develop slot
    close: dict
    warnings: list[str] = field(default_factory=list)


def assign_slots(
    slots: list[dict],
    selected: list[dict],
    candidates_by_id: dict,
    config: dict | None = None,
) -> Assignment:
    """Assign one candidate from `selected` to each slot (hook/develop/close), per #6.2.

    Args:
        slots: Slot dicts, as in `slots.json["slots"]` (each with `slot`,
            `start_f`, `end_f`, `role`, `beats_rel_f`).
        selected: Candidate selections, as returned by
            `selection.build_selected` (see `select_develop` for the entry
            shape).
        candidates_by_id: Mapping `candidate_id -> candidate dict`.
        config: Planner config overrides, merged over `DEFAULT_CONFIG`.

    Returns:
        `Assignment` with the chosen hook/develop/close entries and any
        warnings (currently only `"arc_fallback"`, see `place_develop_arc`).

    Raises:
        PlannerError: If no admissible candidate exists for the hook or
            close slot, or fewer develop candidates were taken than there
            are develop slots (the rules fallback for these cases is out
            of this module's scope; it lives in `selection.py`).
    """
    config = {**DEFAULT_CONFIG, **(config or {})}
    hook_slot = next(s for s in slots if s["role"] == "hook")
    close_slot = next(s for s in slots if s["role"] == "close")
    develop_slots = [s for s in slots if s["role"] == "develop"]

    hook = _select_single(
        selected,
        "hook",
        {"peak"},
        candidates_by_id,
        hook_slot["end_f"] - hook_slot["start_f"],
        config["hook_speed"],
    )
    if hook is None:
        msg = "no admissible hook candidate (rules fallback out of scope here)"
        raise PlannerError(msg)

    # "peak" included because fallback_close (#8.6) uses it as a last
    # resort (close_not_calm) when no calm/image candidate is admissible.
    close = _select_single(
        selected,
        "close",
        {"calm", "image", "peak"},
        candidates_by_id,
        close_slot["end_f"] - close_slot["start_f"],
        1.0,
    )
    if close is None:
        msg = "no admissible close candidate (rules fallback out of scope here)"
        raise PlannerError(msg)

    used = [
        {
            "src": candidates_by_id[hook["candidate_id"]]["src"],
            **{
                k: v
                for k, v in compute_in_out(
                    candidates_by_id[hook["candidate_id"]],
                    hook_slot,
                    "hook",
                    config["hook_speed"],
                    config,
                ).items()
                if k in ("in_s", "out_s")
            },
        }
    ]

    taken = select_develop(selected, candidates_by_id, develop_slots, used, config)
    warnings = []
    if len(taken) < len(develop_slots):
        msg = (
            f"not enough develop candidates ({len(taken)}/{len(develop_slots)}); "
            "rules fallback out of this module's scope"
        )
        raise PlannerError(
            msg,
        )

    placement, arc_fallback = place_develop_arc(taken, hook, close, candidates_by_id)
    if arc_fallback:
        warnings.append("arc_fallback")

    return Assignment(hook=hook, develop=placement, close=close, warnings=warnings)


# --------------------------------------------------------------------------
# 6.3 In/out computation (peak on beat)
# --------------------------------------------------------------------------


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
        role: Slot role (`"hook"`, `"develop"`, `"close"`); `"close"` and
            any `"calm"`-kind candidate center the clip on the slot instead
            of aligning to a beat.
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
    if role == "close" or candidate["kind"] == "calm":
        lead_f = d_f // 2
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


# --------------------------------------------------------------------------
# 6.4 9:16 crop
# --------------------------------------------------------------------------


def compute_crop(
    bbox: tuple[float, float, float, float], w: int, h: int, config: dict
) -> dict:
    """Compute the 9:16 crop centered on the subject bbox, per #6.4.

    Args:
        bbox: `(x0, y0, x1, y1)`, normalized, the subject bbox median over
            `[in_s, out_s]`.
        w: Source width, in pixels.
        h: Source height, in pixels.
        config: Planner config; reads `upscale_threshold` and
            `allow_blur_pad`.

    Returns:
        Dict with keys:
        - `crop` (dict): normalized crop rect `{x, y, w, h}`, all in
          [0, 1].
        - `layout` (str): `"crop"` if the source can be cropped to 9:16
          without excessive upscaling, `"blur_pad"` if it must instead be
          letterboxed over a blurred background (when upscale exceeds
          `config["upscale_threshold"]` and `config["allow_blur_pad"]` is
          set).
        - `subject_cropped` (bool): whether the subject bbox extends
          outside the chosen crop rect (beyond a small tolerance).
        - `warnings` (list[str]): `["upscale_gt_1.3"]` if the crop would
          need more upscaling than `config["upscale_threshold"]`; empty
          otherwise.
    """
    warnings: list[str] = []

    if is_916(w, h):
        return {
            "crop": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0},
            "layout": "crop",
            "subject_cropped": False,
            "warnings": warnings,
        }

    if w / h > 9 / 16:
        h_n, w_n = 1.0, (9 / 16) * h / w
    else:
        w_n, h_n = 1.0, (16 / 9) * w / h

    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    x = max(0.0, min(cx - w_n / 2, 1 - w_n))
    y = max(0.0, min(cy - h_n / 2, 1 - h_n))

    tol = 0.05
    subject_cropped = (
        bbox[0] < x - tol * w_n
        or bbox[2] > x + w_n + tol * w_n
        or bbox[1] < y - tol * h_n
        or bbox[3] > y + h_n + tol * h_n
    )

    upscale = 1080 / (w_n * w)
    layout = "crop"
    if upscale > config["upscale_threshold"]:
        warnings.append("upscale_gt_1.3")
        if config["allow_blur_pad"]:
            layout = "blur_pad"

    return {
        "crop": {"x": x, "y": y, "w": w_n, "h": h_n},
        "layout": layout,
        "subject_cropped": subject_cropped,
        "warnings": warnings,
    }


# --------------------------------------------------------------------------
# 6.6 Per-clip effects
# --------------------------------------------------------------------------


def effect_for(candidate: dict, layout: str, config: dict) -> tuple[str, dict]:
    """Pick the effect and its parameters for a clip, per #6.6.

    Args:
        candidate: Candidate dict; reads `kind`.
        layout: Crop layout for this clip, as returned by `compute_crop`
            (`"crop"` or `"blur_pad"`).
        config: Planner config; reads `ken_burns`, `zoom_per_frame`,
            `zoom_max` (for image candidates), and `blur_radius`,
            `blur_power`, `bg_brightness` (for `blur_pad` layouts).

    Returns:
        `(effect, effect_params)`:
        - `("kenburns", {"zoom_per_frame": ..., "zoom_max": ...})` for
          image candidates when `config["ken_burns"]` is enabled.
        - `("none", {"blur_radius": ..., "blur_power": ...,
          "bg_brightness": ...})` for `blur_pad` layouts.
        - `("none", {})` otherwise.
    """
    if candidate["kind"] == "image" and config.get("ken_burns", True):
        return "kenburns", {
            "zoom_per_frame": config["zoom_per_frame"],
            "zoom_max": config["zoom_max"],
        }
    if layout == "blur_pad":
        return "none", {
            "blur_radius": config["blur_radius"],
            "blur_power": config["blur_power"],
            "bg_brightness": config["bg_brightness"],
        }
    return "none", {}


# --------------------------------------------------------------------------
# 8.2 Planner invariants: asserts, not repairs. A failure here is a planner
# bug; the session stops with PlannerError.
# --------------------------------------------------------------------------


def _assert_invariants(
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
            # P5
            expected_n_frames = round((c["out_s"] - c["in_s"]) / c["speed"] * FPS)
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

        # P9
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


# --------------------------------------------------------------------------
# Orchestration: builds the EDL's `clips` list (#7) from slots, selection,
# and candidates+sources.
# --------------------------------------------------------------------------


def build_clips(
    slots: list[dict],
    selected: list[dict],
    candidates_by_id: dict,
    sources_by_src: dict,
    config: dict | None = None,
) -> tuple[list[dict], list[str]]:
    """Run the full planner pipeline (#6): from slots+selected to EDL clips.

    Args:
        slots: Slot dicts, as in `slots.json["slots"]`.
        selected: Candidate selections, as returned by
            `selection.build_selected`.
        candidates_by_id: Mapping `candidate_id -> candidate dict`.
        sources_by_src: Mapping `src -> source dict` (from
            `manifest.json["sources"]`, keyed by `src`).
        config: Planner config overrides, merged over `DEFAULT_CONFIG`.

    Returns:
        `(clips, warnings)`:
        - `clips`: one dict per slot, in slot order, each with keys `slot`,
          `role`, `candidate_id`, `src`, `src_sha256`, `type`, `src_w`,
          `src_h`, `src_rotation`, `src_color` (dict, see
          `ingest.probe_video_source`'s `color` field), `hdr`, `in_s`,
          `out_s`, `n_frames`, `speed`, `timeline_start_f`,
          `timeline_end_f`, `layout`, `crop`, `crop_px`, `subject_cropped`,
          `src_fps_nominal`, `effect`, `effect_params`, `warnings`
          (list[str], this clip's own warnings only).
        - `warnings`: all warnings accumulated across role assignment,
          timing, and cropping (a flat list, not per-clip).

    Raises:
        PlannerError: If `assign_slots` fails (no admissible hook/close, or
            missing develop candidates), or if the assembled clips violate
            any of invariants P1-P9 (see `_assert_invariants`).
    """
    config = {**DEFAULT_CONFIG, **(config or {})}
    assignment = assign_slots(slots, selected, candidates_by_id, config)
    warnings = list(assignment.warnings)

    per_slot: dict[int, tuple[dict, str, float]] = {}
    hook_slot = next(s for s in slots if s["role"] == "hook")
    close_slot = next(s for s in slots if s["role"] == "close")
    develop_slots = [s for s in slots if s["role"] == "develop"]

    per_slot[hook_slot["slot"]] = (assignment.hook, "hook", config["hook_speed"])
    per_slot[close_slot["slot"]] = (assignment.close, "close", 1.0)
    for slot, sel in zip(develop_slots, assignment.develop, strict=False):
        per_slot[slot["slot"]] = (sel, "develop", 1.0)

    clips: list[dict[str, Any]] = []
    for slot in slots:
        sel, role, speed = per_slot[slot["slot"]]
        cand = candidates_by_id[sel["candidate_id"]]
        src_info = sources_by_src[cand["src"]]

        timing = compute_in_out(cand, slot, role, speed, config)
        warnings.extend(timing["warnings"])

        crop_info = compute_crop(
            tuple(cand["subject_bbox"]), src_info["w"], src_info["h"], config
        )
        warnings.extend(crop_info["warnings"])
        crop_px = crop_to_px(
            crop_info["crop"], src_info["w"], src_info["h"], crop_info["layout"]
        )

        effect, effect_params = effect_for(cand, crop_info["layout"], config)

        clip_warnings = list(timing["warnings"]) + list(crop_info["warnings"])
        clips.append(
            {
                "slot": slot["slot"],
                "role": role,
                "candidate_id": sel["candidate_id"],
                "src": cand["src"],
                "src_sha256": src_info["sha256"],
                "type": src_info["type"],
                "src_w": src_info["w"],
                "src_h": src_info["h"],
                "src_rotation": src_info.get("rotation", 0),
                "src_color": src_info.get(
                    "color",
                    {
                        "primaries": "unknown",
                        "trc": "unknown",
                        "space": "unknown",
                        "range": "unknown",
                    },
                ),
                "hdr": src_info.get("hdr", "none"),
                "in_s": timing["in_s"],
                "out_s": timing["out_s"],
                "n_frames": timing["n_frames"],
                "speed": speed,
                "timeline_start_f": timing["timeline_start_f"],
                "timeline_end_f": timing["timeline_end_f"],
                "layout": crop_info["layout"],
                "crop": crop_info["crop"],
                "crop_px": crop_px,
                "subject_cropped": crop_info["subject_cropped"],
                "src_fps_nominal": src_info.get("src_fps_nominal", FPS),
                "effect": effect,
                "effect_params": effect_params,
                "warnings": clip_warnings,
            }
        )

    clips.sort(key=lambda c: c["slot"])
    _assert_invariants(clips, slots, candidates_by_id, sources_by_src)
    return clips, warnings
