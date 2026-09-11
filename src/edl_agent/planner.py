"""Capa 4 - Planner determinista (snapper).

Ver docs/architecture/arquitectura_edl_agent_v4.md #6. El LLM decide que
(candidatos, rol, rank, exercise); este modulo decide cuando y donde: frames
exactos, alineacion a beat, orden de los develop, crop en pixeles.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .render import crop_to_px, is_916

FPS = 30


class PlannerError(RuntimeError):
    """Invariante del planner violado o rol sin candidato admisible (#0, #8.2)."""


DEFAULT_CONFIG = {
    "hook_speed": 1.0,          # unico rol donde 0.5 esta permitido (#6)
    "peak_beat_index": 1,       # #6.3: pico en el 2o beat del slot por defecto
    "allow_blur_pad": True,     # #6.4
    "upscale_threshold": 1.3,
    "ken_burns": True,          # #6.6
    "zoom_per_frame": 0.0015,
    "zoom_max": 1.08,
    "blur_radius": 20,
    "blur_power": 2,
    "bg_brightness": -0.1,
    "adjacency_gap_s": 0.25,    # #6.2.3 margen anti-solape misma fuente
}


# --------------------------------------------------------------------------
# 6.1 Admision de un candidato en un slot
# --------------------------------------------------------------------------

def admits(window: tuple[float, float], d_f: int, speed: float) -> bool:
    need_s = d_f / FPS * speed
    return (window[1] - window[0]) >= need_s + 2 / FPS


# --------------------------------------------------------------------------
# 6.2 Asignacion
# --------------------------------------------------------------------------

def _norm_exercise(exercise: str) -> str:
    return exercise.lower().strip()


def _select_single(selected: list[dict], role: str, kinds: set[str] | None,
                    candidates_by_id: dict, d_f: int, speed: float) -> dict | None:
    pool = sorted(
        (s for s in selected if s["role"] == role
         and (kinds is None or candidates_by_id[s["candidate_id"]]["kind"] in kinds)),
        key=lambda s: s["rank"],
    )
    for s in pool:
        cand = candidates_by_id[s["candidate_id"]]
        if admits(tuple(cand["window"]), d_f, speed):
            return s
    return None


def _overlaps_used(cand: dict, in_s: float, out_s: float, used: list[dict], gap_s: float) -> bool:
    for u in used:
        if u["src"] != cand["src"]:
            continue
        if in_s < u["out_s"] + gap_s and u["in_s"] < out_s + gap_s:
            return True
    return False


def select_develop(
    selected: list[dict], candidates_by_id: dict, develop_slots: list[dict],
    used: list[dict], config: dict,
) -> list[dict]:
    """#6.2.3. Devuelve la lista de entradas `selected` tomadas para develop,
    en orden de rank (r1 = mejor). El orden temporal final lo decide #6.2.4."""
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
        admissible_d_f = next((d for d in free_durations if admits(tuple(cand["window"]), d, 1.0)), None)
        if admissible_d_f is None:
            continue
        if prev_exercise is not None and _norm_exercise(s["exercise"]) == prev_exercise:
            continue
        if prev_src is not None and cand["src"] == prev_src:
            continue
        timing = compute_in_out(cand, {"start_f": 0, "end_f": admissible_d_f, "beats_rel_f": [0]},
                                 role="develop", speed=1.0, config=config)
        if _overlaps_used(cand, timing["in_s"], timing["out_s"], used, config["adjacency_gap_s"]):
            continue
        taken.append(s)
        used.append({"src": cand["src"], "in_s": timing["in_s"], "out_s": timing["out_s"]})
        free_durations.remove(admissible_d_f)
        prev_exercise = _norm_exercise(s["exercise"])
        prev_src = cand["src"]
    return taken


def arc_order(k: int) -> list[int]:
    """#6.2.4. Devuelve, para cada slot develop s1..sk (0-indexado), el rank
    (1-indexado) del candidato que le corresponde."""
    evens = list(range(2, k + 1, 2))
    odds = list(range(1, k + 1, 2))
    return evens + odds[::-1]


def _adjacency_violations(chain: list[dict | None], candidates_by_id: dict) -> list[int]:
    """Indices i tales que chain[i] y chain[i+1] repiten ejercicio o src."""
    bad = []
    for i in range(len(chain) - 1):
        a, b = chain[i], chain[i + 1]
        if a is None or b is None:
            continue
        ca, cb = candidates_by_id[a["candidate_id"]], candidates_by_id[b["candidate_id"]]
        if _norm_exercise(a["exercise"]) == _norm_exercise(b["exercise"]) or ca["src"] == cb["src"]:
            bad.append(i)
    return bad


def place_develop_arc(
    taken: list[dict], hook: dict | None, close: dict | None, candidates_by_id: dict,
) -> tuple[list[dict], bool]:
    """#6.2.4. Devuelve (placement en orden s1..sk, arc_fallback: bool)."""
    k = len(taken)
    if k == 0:
        return [], False
    by_rank = {i + 1: s for i, s in enumerate(taken)}  # taken ya viene ordenado por rank
    order = arc_order(k)
    placement = [by_rank[r] for r in order]

    for _ in range(3):
        chain = [hook, *placement, close]
        violations = _adjacency_violations(chain, candidates_by_id)
        # +1 porque chain incluye hook en la posicion 0
        dev_violations = [i for i in violations if 0 < i < len(chain) - 1]
        if not violations:
            return placement, False
        if not dev_violations:
            break  # violacion solo contra hook/close: no se puede arreglar intercambiando develops
        i = dev_violations[0]
        dev_i = i - 1  # indice dentro de `placement`
        if dev_i + 1 < len(placement):
            placement[dev_i], placement[dev_i + 1] = placement[dev_i + 1], placement[dev_i]

    chain = [hook, *placement, close]
    if _adjacency_violations(chain, candidates_by_id):
        return list(taken), True  # #6.2.4: orden de rank, warning: arc_fallback
    return placement, False


# --------------------------------------------------------------------------
# 6.2.5 Relajacion. Implementada en selection.build_selected: si hook/close
# no tienen candidato admisible libre, se reclama (preempt) uno ya asignado
# a develop -- mas flexible (N slots, tipicamente mas candidatos) -- y el
# hueco que deja se intenta rellenar con el pool de fallback restante. Solo
# cubre develop -> hook/close; si develop se queda corto sin nada que lo
# rellene, este modulo sigue lanzando PlannerError mas abajo.
# --------------------------------------------------------------------------

@dataclass
class Assignment:
    hook: dict
    develop: list[dict]  # en orden s1..sk, uno por slot develop
    close: dict
    warnings: list[str] = field(default_factory=list)


def assign_slots(slots: list[dict], selected: list[dict], candidates_by_id: dict,
                  config: dict | None = None) -> Assignment:
    config = {**DEFAULT_CONFIG, **(config or {})}
    hook_slot = next(s for s in slots if s["role"] == "hook")
    close_slot = next(s for s in slots if s["role"] == "close")
    develop_slots = [s for s in slots if s["role"] == "develop"]

    hook = _select_single(selected, "hook", {"peak"}, candidates_by_id,
                           hook_slot["end_f"] - hook_slot["start_f"], config["hook_speed"])
    if hook is None:
        raise PlannerError("no admissible hook candidate (fallback de reglas fuera de alcance)")

    # "peak" incluido porque fallback_close (#8.6) lo usa como ultimo recurso
    # (close_not_calm) cuando no hay calm/image admisible.
    close = _select_single(selected, "close", {"calm", "image", "peak"}, candidates_by_id,
                            close_slot["end_f"] - close_slot["start_f"], 1.0)
    if close is None:
        raise PlannerError("no admissible close candidate (fallback de reglas fuera de alcance)")

    used = [{
        "src": candidates_by_id[hook["candidate_id"]]["src"],
        **{k: v for k, v in compute_in_out(
            candidates_by_id[hook["candidate_id"]], hook_slot, "hook", config["hook_speed"], config,
        ).items() if k in ("in_s", "out_s")},
    }]

    taken = select_develop(selected, candidates_by_id, develop_slots, used, config)
    warnings = []
    if len(taken) < len(develop_slots):
        raise PlannerError(
            f"not enough develop candidates ({len(taken)}/{len(develop_slots)}); "
            "fallback de reglas fuera de alcance de este modulo"
        )

    placement, arc_fallback = place_develop_arc(taken, hook, close, candidates_by_id)
    if arc_fallback:
        warnings.append("arc_fallback")

    return Assignment(hook=hook, develop=placement, close=close, warnings=warnings)


# --------------------------------------------------------------------------
# 6.3 Calculo de in/out (pico sobre beat)
# --------------------------------------------------------------------------

def compute_in_out(candidate: dict, slot: dict, role: str, speed: float, config: dict) -> dict:
    d_f = slot["end_f"] - slot["start_f"]
    need_s = d_f / FPS * speed
    warnings: list[str] = []

    if candidate["kind"] == "image":
        return {
            "in_s": 0.0, "out_s": d_f / FPS, "n_frames": d_f,
            "timeline_start_f": slot["start_f"], "timeline_end_f": slot["end_f"],
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
        "in_s": in_s, "out_s": out_s, "n_frames": d_f,
        "timeline_start_f": slot["start_f"], "timeline_end_f": slot["end_f"],
        "warnings": warnings,
    }


# --------------------------------------------------------------------------
# 6.4 Crop 9:16
# --------------------------------------------------------------------------

def compute_crop(bbox: tuple[float, float, float, float], w: int, h: int, config: dict) -> dict:
    """bbox = (x0,y0,x1,y1) normalizado, mediana en [in_s,out_s]. Devuelve
    crop normalizado + layout + warnings (#6.4)."""
    warnings: list[str] = []

    if is_916(w, h):
        return {"crop": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}, "layout": "crop",
                "subject_cropped": False, "warnings": warnings}

    if w / h > 9 / 16:
        h_n, w_n = 1.0, (9 / 16) * h / w
    else:
        w_n, h_n = 1.0, (16 / 9) * w / h

    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    x = max(0.0, min(cx - w_n / 2, 1 - w_n))
    y = max(0.0, min(cy - h_n / 2, 1 - h_n))

    tol = 0.05
    subject_cropped = (
        bbox[0] < x - tol * w_n or bbox[2] > x + w_n + tol * w_n
        or bbox[1] < y - tol * h_n or bbox[3] > y + h_n + tol * h_n
    )

    upscale = 1080 / (w_n * w)
    layout = "crop"
    if upscale > config["upscale_threshold"]:
        warnings.append("upscale_gt_1.3")
        if config["allow_blur_pad"]:
            layout = "blur_pad"

    return {"crop": {"x": x, "y": y, "w": w_n, "h": h_n}, "layout": layout,
            "subject_cropped": subject_cropped, "warnings": warnings}


# --------------------------------------------------------------------------
# 6.6 Efectos por clip
# --------------------------------------------------------------------------

def effect_for(candidate: dict, layout: str, config: dict) -> tuple[str, dict]:
    if candidate["kind"] == "image" and config.get("ken_burns", True):
        return "kenburns", {"zoom_per_frame": config["zoom_per_frame"], "zoom_max": config["zoom_max"]}
    if layout == "blur_pad":
        return "none", {"blur_radius": config["blur_radius"], "blur_power": config["blur_power"],
                         "bg_brightness": config["bg_brightness"]}
    return "none", {}


# --------------------------------------------------------------------------
# 8.2 Invariantes del planner: asserts, no reparaciones. Un fallo aqui es un
# bug del planner; la sesion se detiene con PlannerError.
# --------------------------------------------------------------------------

def _assert_invariants(
    clips: list[dict], slots: list[dict], candidates_by_id: dict, sources_by_src: dict,
) -> None:
    n_slots = len(slots)

    # P1
    if len(clips) != n_slots or [c["slot"] for c in clips] != [s["slot"] for s in slots]:
        raise PlannerError("P1: clips no cubren los slots 1:1 en orden")

    # P2
    if len({c["candidate_id"] for c in clips}) != len(clips):
        raise PlannerError("P2: candidate_id repetido entre clips")

    for c in clips:
        if c["type"] != "image":
            # P3
            window = candidates_by_id[c["candidate_id"]]["window"]
            if not (window[0] - 1e-6 <= c["in_s"] and c["out_s"] <= window[1] + 1e-6):
                raise PlannerError(f"P3: in_s/out_s fuera de window en slot {c['slot']}")
            # P4
            duration_s = sources_by_src[c["src"]]["duration_s"]
            if not (0 <= c["in_s"] < c["out_s"] <= duration_s + 1e-6):
                raise PlannerError(f"P4: in_s/out_s invalido en slot {c['slot']}")
            # P5
            expected_n_frames = round((c["out_s"] - c["in_s"]) / c["speed"] * FPS)
            if expected_n_frames != c["n_frames"]:
                raise PlannerError(f"P5: n_frames no coincide en slot {c['slot']}")

        # P8
        crop = c["crop"]
        if not (0 <= crop["x"] <= 1 and 0 <= crop["y"] <= 1 and 0 < crop["w"] <= 1 and 0 < crop["h"] <= 1):
            raise PlannerError(f"P8: crop fuera de [0,1] en slot {c['slot']}")
        px = c["crop_px"]
        if not (0 <= px["x"] and px["x"] + px["w"] <= c["src_w"]
                and 0 <= px["y"] and px["y"] + px["h"] <= c["src_h"]):
            raise PlannerError(f"P8: crop_px fuera de W x H en slot {c['slot']}")
        if px["w"] % 2 != 0 or px["h"] % 2 != 0:
            raise PlannerError(f"P8: crop_px impar en slot {c['slot']}")
        if c["layout"] == "crop" and abs(px["w"] / px["h"] - 9 / 16) * px["h"] > 2:
            raise PlannerError(f"P8: crop_px no respeta 9:16 en slot {c['slot']}")

        # P9
        if c["n_frames"] < 30:
            raise PlannerError(f"P9: n_frames < 30 en slot {c['slot']}")

    # P6
    if clips[0]["timeline_start_f"] != 0:
        raise PlannerError("P6: timeline_start_f[0] != 0")
    if clips[-1]["timeline_end_f"] != slots[-1]["end_f"]:
        raise PlannerError("P6: timeline_end_f[-1] != duration_f")
    for a, b in zip(clips, clips[1:]):
        if a["timeline_end_f"] != b["timeline_start_f"]:
            raise PlannerError(f"P6: hueco en la timeline entre slots {a['slot']} y {b['slot']}")
    if sum(c["n_frames"] for c in clips) != slots[-1]["end_f"]:
        raise PlannerError("P6: sum(n_frames) != duration_f")

    # P7: sin solapes de la misma fuente (margen 0.25s)
    by_src: dict[str, list[dict]] = {}
    for c in clips:
        if c["type"] != "image":
            by_src.setdefault(c["src"], []).append(c)
    for segs in by_src.values():
        segs = sorted(segs, key=lambda c: c["in_s"])
        for a, b in zip(segs, segs[1:]):
            if a["out_s"] + 0.25 > b["in_s"] + 1e-6:
                raise PlannerError(f"P7: solape de la misma fuente {a['src']}")


# --------------------------------------------------------------------------
# Orquestacion: construye la lista `clips` del EDL (#7) a partir de slots,
# selection y candidatos+fuentes.
# --------------------------------------------------------------------------

def build_clips(
    slots: list[dict], selected: list[dict], candidates_by_id: dict,
    sources_by_src: dict, config: dict | None = None,
) -> tuple[list[dict], list[str]]:
    config = {**DEFAULT_CONFIG, **(config or {})}
    assignment = assign_slots(slots, selected, candidates_by_id, config)
    warnings = list(assignment.warnings)

    per_slot: dict[int, tuple[dict, str, float]] = {}
    hook_slot = next(s for s in slots if s["role"] == "hook")
    close_slot = next(s for s in slots if s["role"] == "close")
    develop_slots = [s for s in slots if s["role"] == "develop"]

    per_slot[hook_slot["slot"]] = (assignment.hook, "hook", config["hook_speed"])
    per_slot[close_slot["slot"]] = (assignment.close, "close", 1.0)
    for slot, sel in zip(develop_slots, assignment.develop):
        per_slot[slot["slot"]] = (sel, "develop", 1.0)

    clips = []
    for slot in slots:
        sel, role, speed = per_slot[slot["slot"]]
        cand = candidates_by_id[sel["candidate_id"]]
        src_info = sources_by_src[cand["src"]]

        timing = compute_in_out(cand, slot, role, speed, config)
        warnings.extend(timing["warnings"])

        crop_info = compute_crop(tuple(cand["subject_bbox"]), src_info["w"], src_info["h"], config)
        warnings.extend(crop_info["warnings"])
        crop_px = crop_to_px(crop_info["crop"], src_info["w"], src_info["h"], crop_info["layout"])

        effect, effect_params = effect_for(cand, crop_info["layout"], config)

        clip_warnings = list(timing["warnings"]) + list(crop_info["warnings"])
        clips.append({
            "slot": slot["slot"], "role": role, "candidate_id": sel["candidate_id"],
            "src": cand["src"], "src_sha256": src_info["sha256"], "type": src_info["type"],
            "src_w": src_info["w"], "src_h": src_info["h"], "src_rotation": src_info.get("rotation", 0),
            "src_color": src_info.get("color", {"primaries": "unknown", "trc": "unknown",
                                                  "space": "unknown", "range": "unknown"}),
            "hdr": src_info.get("hdr", "none"),
            "in_s": timing["in_s"], "out_s": timing["out_s"], "n_frames": timing["n_frames"],
            "speed": speed,
            "timeline_start_f": timing["timeline_start_f"], "timeline_end_f": timing["timeline_end_f"],
            "layout": crop_info["layout"], "crop": crop_info["crop"], "crop_px": crop_px,
            "subject_cropped": crop_info["subject_cropped"],
            "src_fps_nominal": src_info.get("src_fps_nominal", FPS),
            "effect": effect, "effect_params": effect_params,
            "warnings": clip_warnings,
        })

    clips.sort(key=lambda c: c["slot"])
    _assert_invariants(clips, slots, candidates_by_id, sources_by_src)
    return clips, warnings
