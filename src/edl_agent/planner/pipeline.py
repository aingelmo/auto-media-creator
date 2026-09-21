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
            With `config["end_card"]`, the close clip's tail carries the
            C0 brand sign-off (`_apply_outro`, never skipped).

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
            any of invariants P1-P9 (see `invariants.assert_invariants`).
    """
    config = {**DEFAULT_CONFIG, **(config or {})}
    assignment = assign_slots(slots, selected, candidates_by_id, config)
    warnings = list(assignment.warnings)

    per_slot: dict[int, tuple[dict, str, dict | None, int | None]] = {}
    hook_slot = next(s for s in slots if s["role"] == "hook")
    close_slot = next(s for s in slots if s["role"] == "close")
    develop_slots = [s for s in slots if s["role"] == "develop"]

    # ponytail: ramp only on the hook; per-develop ramps make the reel feel slow.
    per_slot[hook_slot["slot"]] = (assignment.hook, "hook", hook_ramp(config), None)
    per_slot[close_slot["slot"]] = (assignment.close, "close", None, None)
    develop_pairs = zip(develop_slots, assignment.develop, strict=False)
    for i, (slot, sel) in enumerate(develop_pairs):
        per_slot[slot["slot"]] = (sel, "develop", None, i)

    clips: list[dict[str, Any]] = []
    for slot in slots:
        sel, role, ramp, develop_i = per_slot[slot["slot"]]
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

        hook_text: tuple[str, int] | None = None
        if role == "hook":
            hook_text = (str(config["hook_line_override"]), int(timing["n_frames"]))
        clip_config = config
        if role == "develop":
            if develop_i is None:
                msg = "develop role requires a develop index"
                raise ValueError(msg)
            punch_every = int(config["punch_every"])
            punch_in = config["punch_in"] and develop_i % punch_every == 0
            clip_config = config | {"punch_in": punch_in}
        effect, effect_params = effect_for(
            cand,
            crop_info["layout"],
            clip_config,
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
    if brand and config["end_card"]:
        _apply_outro(clips[-1], config, brand)
    assert_invariants(clips, slots, candidates_by_id, sources_by_src)
    return clips, warnings


def _apply_outro(close: dict, config: dict, brand: dict) -> None:
    """Burn the C0 brand sign-off into the close clip's tail (#6.8).

    No timeline is stolen: the close keeps all its frames and its last
    `k = min(end_card_frames, n_frames)` frames double as the outro
    (blurred/dimmed background with the logo + handle overlaid, see
    `render.finish_graph`). P9 guarantees the close holds >= 30 frames,
    so the full 24-frame tail always fits and the card can never be
    skipped for lack of room.

    Args:
        close: Close clip dict, mutated in place (only `effect_params`
            gains `outro_*` keys).
        config: Merged planner config; reads `end_card_frames`,
            `end_card_logo_w`, `end_card_text_size`, `blur_radius`,
            `blur_power`.
        brand: `edl["brand"]`; reads `fg`, `font`, `handle`, `logo`
            (session-relative), `logo_w`, `logo_h`.
    """
    k = min(config["end_card_frames"], close["n_frames"])
    close["effect_params"].update(
        {
            "outro_frames": k,
            "outro_fg": brand["fg"],
            "outro_font": brand["font"],
            "outro_handle": brand["handle"],
            "outro_logo_src": brand["logo"],
            "outro_logo_w": config["end_card_logo_w"],
            "outro_logo_h": round(
                brand["logo_h"] * config["end_card_logo_w"] / brand["logo_w"]
            ),
            "outro_text_size": config["end_card_text_size"],
            "outro_blur_radius": config["blur_radius"],
            "outro_blur_power": config["blur_power"],
            "outro_dim": -0.3,
        }
    )
