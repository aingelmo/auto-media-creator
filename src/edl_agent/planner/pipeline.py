"""Orchestration: builds the EDL's `clips` list (#7).

From slots, selection, and candidates+sources.
"""

from __future__ import annotations

from typing import Any

from edl_agent.planner._common import DEFAULT_CONFIG, FPS, hook_ramp
from edl_agent.planner.assignment import assign_slots
from edl_agent.planner.crop import compute_crop
from edl_agent.planner.effects import effect_for
from edl_agent.planner.invariants import assert_invariants
from edl_agent.planner.timing import compute_in_out
from edl_agent.render import crop_to_px


def build_clips(
    slots: list[dict],
    selected: list[dict],
    candidates_by_id: dict,
    sources_by_src: dict,
    config: dict | None = None,
    brand: dict | None = None,
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
        brand: `edl["brand"]` (see `session.planner.load_brand`) or `None`.
            With `config["end_card"]`, the close clip gives its last
            `end_card_frames` to a synthetic `role == "end_card"` clip
            (`_split_end_card`); warns `end_card_skipped` if the close is
            too short.

    Returns:
        `(clips, warnings)`:
        - `clips`: one dict per slot, in slot order (plus the end card,
          if any), each with keys `slot`,
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
            any of invariants P1-P9 (see `invariants.assert_invariants`).
    """
    config = {**DEFAULT_CONFIG, **(config or {})}
    assignment = assign_slots(slots, selected, candidates_by_id, config)
    warnings = list(assignment.warnings)

    per_slot: dict[int, tuple[dict, str, dict | None]] = {}
    hook_slot = next(s for s in slots if s["role"] == "hook")
    close_slot = next(s for s in slots if s["role"] == "close")
    develop_slots = [s for s in slots if s["role"] == "develop"]

    # ponytail: ramp only on the hook; per-develop ramps make the reel feel slow.
    per_slot[hook_slot["slot"]] = (assignment.hook, "hook", hook_ramp(config))
    per_slot[close_slot["slot"]] = (assignment.close, "close", None)
    for slot, sel in zip(develop_slots, assignment.develop, strict=False):
        per_slot[slot["slot"]] = (sel, "develop", None)

    clips: list[dict[str, Any]] = []
    for slot in slots:
        sel, role, ramp = per_slot[slot["slot"]]
        cand = candidates_by_id[sel["candidate_id"]]
        src_info = sources_by_src[cand["src"]]

        timing = compute_in_out(cand, slot, role, ramp, config)
        warnings.extend(timing["warnings"])

        crop_info = compute_crop(
            tuple(cand["subject_bbox"]), src_info["w"], src_info["h"], config
        )
        warnings.extend(crop_info["warnings"])
        crop_px = crop_to_px(
            crop_info["crop"], src_info["w"], src_info["h"], crop_info["layout"]
        )

        hook_text = None
        if role == "hook":
            hook_text = (config["hook_line_override"], timing["n_frames"])
        effect, effect_params = effect_for(
            cand,
            crop_info["layout"],
            config,
            timing["ramp"],
            hook_text,
            role=role,
            peak_f=timing["peak_f"],
        )

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
                "speed": 1.0,  # EDL back-compat; the ramp lives in effect_params
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
    extra_slots: list[dict] = []
    if brand and config["end_card"]:
        end_slot = _split_end_card(clips, config, brand)
        if end_slot is None:
            warnings.append("end_card_skipped")
        else:
            extra_slots.append(end_slot)
    assert_invariants(clips, slots + extra_slots, candidates_by_id, sources_by_src)
    return clips, warnings


def _split_end_card(clips: list[dict], config: dict, brand: dict) -> dict | None:
    """Move the last `end_card_frames` of the close clip into an `end_card` clip (#6.8).

    The close keeps >= 30 frames (P9); the card needs >= 15 or it is
    skipped (returns `None`). Returns the synthetic slot for P1/P6.
    """
    close = clips[-1]
    k = min(config["end_card_frames"], close["n_frames"] - 30)
    if k < 15:
        return None
    close["n_frames"] -= k
    close["out_s"] = close["in_s"] + close["n_frames"] / FPS  # close is 1.0x
    close["timeline_end_f"] -= k
    start_f = close["timeline_end_f"]
    # ponytail: the card's "source" is the 1080x1920 canvas, so crop is full-frame
    # and 9:16 by construction; the logo path in `src` is what the render reads.
    clips.append(
        {
            "slot": close["slot"] + 1,
            "role": "end_card",
            "candidate_id": "end_card",
            "src": brand["logo"],
            "src_sha256": brand["logo_sha256"],
            "type": "image",
            "src_w": 1080,
            "src_h": 1920,
            "src_rotation": 0,
            "src_color": {
                "primaries": "bt709",
                "trc": "bt709",
                "space": "bt709",
                "range": "tv",
            },
            "hdr": "none",
            "in_s": 0.0,
            "out_s": k / FPS,
            "n_frames": k,
            "speed": 1.0,
            "timeline_start_f": start_f,
            "timeline_end_f": start_f + k,
            "layout": "crop",
            "crop": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0},
            "crop_px": {"x": 0, "y": 0, "w": 1080, "h": 1920},
            "subject_cropped": False,
            "src_fps_nominal": FPS,
            "effect": "end_card",
            "effect_params": {
                "bg": brand["bg"],
                "fg": brand["fg"],
                "font": brand["font"],
                "handle": brand["handle"],
                "line": brand["line"],
                "logo_w": config["end_card_logo_w"],
                "logo_h": round(
                    brand["logo_h"] * config["end_card_logo_w"] / brand["logo_w"]
                ),
                "text_size": config["end_card_text_size"],
            },
            "warnings": [],
        }
    )
    return {
        "slot": close["slot"] + 1,
        "role": "end_card",
        "start_f": start_f,
        "end_f": start_f + k,
        "beats_rel_f": [],
    }
