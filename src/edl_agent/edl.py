"""Capa 4 (salida) - Ensambla edl.json (#7) a partir de manifest, candidates.json,
slots.json y una seleccion (LLM o fallback de reglas, #8.5).
"""
from __future__ import annotations

import hashlib
import json

from .planner import DEFAULT_CONFIG, build_clips
from .render import get_render_profile
from .selection import build_selected

VERSION = 4

DEFAULT_AUDIO_TARGETS = {"target_lufs": -14.0, "target_tp": -1.0, "target_lra": 11.0, "fade_out_s": 0.5}


def _hash(obj: dict) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _audio_block(manifest: dict, config: dict) -> dict:
    music = manifest.get("music")
    return {
        "music_cut_path": music["cut"] if music else None,
        "music_cut_sha256": music["cut_sha256"] if music else None,
        "music_src_path": music["src"] if music else None,
        "music_src_sha256": music["src_sha256"] if music else None,
        "music_offset_s": music["offset_s"] if music else 0.0,
        "target_lufs": config["target_lufs"],
        "target_tp": config["target_tp"],
        "target_lra": config["target_lra"],
        "loudnorm_measured": None,
        "loudnorm_applied": None,
        "fade_out_s": config["fade_out_s"],
    }


_RELAXED_LOW_MATERIAL = ("relaxed_4", "relaxed_5")


def _aggregate_warnings(clips: list[dict], warnings: list[str]) -> list[str]:
    """#8.3 W1-W5: checks compuestos sobre el conjunto de clips, no bloquean
    pero obligan a revisar el preview."""
    agg: list[str] = []

    cropped = sum(1 for c in clips if c["subject_cropped"])
    upscaled = sum(1 for c in clips if "upscale_gt_1.3" in c["warnings"])
    if cropped > 3 or upscaled > 3:
        agg.append("low_framing_quality")

    relaxed = sum(1 for w in warnings if w in _RELAXED_LOW_MATERIAL)
    relaxed += sum(1 for c in clips for w in c["warnings"] if w in _RELAXED_LOW_MATERIAL)
    if relaxed > len(clips) / 2:
        agg.append("low_material_quality")

    peak_off_beat_clips = sum(1 for c in clips if "peak_off_beat" in c["warnings"])
    if "arc_fallback" in warnings or peak_off_beat_clips >= 2:
        agg.append("weak_rhythm")

    hook = next((c for c in clips if c["role"] == "hook"), None)
    if hook is not None and hook["speed"] == 0.5 and hook["src_fps_nominal"] <= 30:
        agg.append("slowmo_duplicates")

    if "sharpness_cross_clip" in warnings:
        agg.append("sharpness_cross_clip")

    return agg


def _provenance(fallback_roles: list[str], has_develop: bool, warnings: list[str], selection_meta: dict | None) -> dict:
    roles_in_use = {"hook", "close"} | ({"develop"} if has_develop else set())
    if not fallback_roles:
        planner_mode = "llm"
    elif set(fallback_roles) >= roles_in_use:
        planner_mode = "rules_fallback"
    else:
        planner_mode = "mixed"

    meta = selection_meta or {}
    return {
        "planner": planner_mode,
        "fallback_roles": fallback_roles,
        "model": meta.get("model"),
        "sdk_version": meta.get("sdk_version"),
        "api_revision": meta.get("api_revision"),
        "llm_attempts": meta.get("llm_attempts", 0),
        "llm_usage": meta.get("llm_usage"),
        "llm_cost_usd": meta.get("llm_cost_usd", 0.0),
        "warnings": warnings,
    }


def build_edl(
    session_id: str,
    manifest: dict,
    candidates_json: dict,
    slots_json: dict,
    selection: dict | None = None,
    selection_meta: dict | None = None,
    manifest_path: str = "manifest.json",
    threads: int = 4,
    tonemap_chain: str = "",
    tonemap_chain_pq: str | None = None,
    config: dict | None = None,
) -> dict:
    """#8.5 completo: selection -> S-checks/fallback -> planner -> edl.json."""
    config = {**DEFAULT_CONFIG, **DEFAULT_AUDIO_TARGETS, **(config or {})}
    slots = slots_json["slots"]
    has_develop = any(s["role"] == "develop" for s in slots)

    selected, warnings, fallback_roles = build_selected(candidates_json, slots_json, selection)

    candidates_by_id = {c["id"]: c for c in candidates_json["candidates"]}
    sources_by_src = {s["src"]: s for s in manifest["sources"]}
    clips, clip_warnings = build_clips(slots, selected, candidates_by_id, sources_by_src, config)
    warnings = warnings + clip_warnings
    warnings = warnings + _aggregate_warnings(clips, warnings)

    render_profile = get_render_profile(threads, tonemap_chain, tonemap_chain_pq)

    return {
        "version": VERSION,
        "session_id": session_id,
        "inputs": {
            "manifest_path": manifest_path,
            "manifest_sha256": _hash(manifest),
            "candidates_sha256": _hash(candidates_json),
            "selection_sha256": _hash(selection) if selection is not None else None,
            "slots_sha256": _hash(slots_json),
            "features_config_sha256": candidates_json.get("features_config_sha256", ""),
            "pose_model_sha256": candidates_json.get("pose_model_sha256", ""),
        },
        "render_profile": render_profile,
        "target": {"w": 1080, "h": 1920, "fps": 30, "duration_f": slots_json["duration_f"]},
        "clips": clips,
        "audio": _audio_block(manifest, config),
        "provenance": _provenance(fallback_roles, has_develop, warnings, selection_meta),
    }
