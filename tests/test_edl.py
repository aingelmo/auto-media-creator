"""#7 Ensamblado de edl.json a partir de manifest/candidates/slots/selection."""
from __future__ import annotations

from edl_agent.edl import build_edl


def _source(src, w=1080, h=1920):
    return {
        "src": src, "sha256": f"sha-{src}", "type": "video", "w": w, "h": h,
        "rotation": 0, "hdr": "none",
        "color": {"primaries": "bt709", "trc": "bt709", "space": "bt709", "range": "tv"},
        "duration_s": 20.0,
    }


def _cand(cid, src, kind, kp_speed=0.5, motion_bg=0.1, sharpness=0.8,
          bbox=(0.3, 0.1, 0.7, 0.9), t_peak=5.0, window=(0.0, 15.0)):
    return {
        "id": cid, "src": src, "kind": kind, "t_peak": t_peak, "window": list(window),
        "kp_speed": kp_speed, "motion_bg": motion_bg, "sharpness": sharpness,
        "subject_bbox": list(bbox), "multi_subject": False, "score_cv": 0.5,
        "admits_slots": [0, 1, 2],
    }


def _manifest(with_music=True):
    return {
        "session_id": "s1",
        "sources": [_source("a.mov"), _source("b.mov"), _source("c.mov")],
        "music": {
            "src": "music/track.mp3", "src_sha256": "musrc", "offset_s": 0.0,
            "max_duration_s": 10.0, "cut": "music/track_cut.wav", "cut_sha256": "muscut",
        } if with_music else None,
    }


def _slots_json():
    return {
        "duration_f": 150,
        "slots": [
            {"slot": 0, "start_f": 0, "end_f": 50, "role": "hook", "beats_rel_f": [0, 25]},
            {"slot": 1, "start_f": 50, "end_f": 100, "role": "develop", "beats_rel_f": [0, 25]},
            {"slot": 2, "start_f": 100, "end_f": 150, "role": "close", "beats_rel_f": [0, 25]},
        ],
    }


def _candidates_json():
    return {
        "features_config_sha256": "feat-hash",
        "pose_model_sha256": "pose-hash",
        "candidates": [
            _cand("c1", "a.mov", "peak", kp_speed=0.9, sharpness=0.9),
            _cand("c2", "b.mov", "calm", sharpness=0.9),
            _cand("c3", "c.mov", "peak", t_peak=6.0),
        ],
    }


def test_build_edl_full_rules_fallback_has_required_top_level_keys():
    edl = build_edl(
        session_id="s1", manifest=_manifest(), candidates_json=_candidates_json(),
        slots_json=_slots_json(), selection=None,
    )
    for key in ("version", "session_id", "inputs", "render_profile", "target", "clips", "audio", "provenance"):
        assert key in edl
    assert edl["version"] == 4
    assert edl["target"] == {"w": 1080, "h": 1920, "fps": 30, "duration_f": 150}
    assert len(edl["clips"]) == 3
    assert edl["inputs"]["selection_sha256"] is None
    assert edl["provenance"]["planner"] == "rules_fallback"
    assert set(edl["provenance"]["fallback_roles"]) == {"hook", "develop", "close"}


def test_build_edl_llm_selection_no_fallback():
    selection = {
        "selected": [
            {"candidate_id": "c1", "role": "hook", "rank": 1, "exercise": "back squat", "reason": "x"},
            {"candidate_id": "c3", "role": "develop", "rank": 1, "exercise": "deadlift", "reason": "x"},
            {"candidate_id": "c2", "role": "close", "rank": 1, "exercise": "other", "reason": "x"},
        ],
        "rejected": [],
        "notes": "",
    }
    edl = build_edl(
        session_id="s1", manifest=_manifest(), candidates_json=_candidates_json(),
        slots_json=_slots_json(), selection=selection,
        selection_meta={"model": "gemini-3.7-flash", "llm_attempts": 1},
    )
    assert edl["provenance"]["planner"] == "llm"
    assert edl["provenance"]["fallback_roles"] == []
    assert edl["provenance"]["model"] == "gemini-3.7-flash"
    assert edl["inputs"]["selection_sha256"] is not None


def test_build_edl_without_music_has_null_audio_paths():
    edl = build_edl(
        session_id="s1", manifest=_manifest(with_music=False), candidates_json=_candidates_json(),
        slots_json=_slots_json(), selection=None,
    )
    assert edl["audio"]["music_cut_path"] is None
    assert edl["audio"]["music_src_path"] is None
