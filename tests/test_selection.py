"""#8.1 S-checks y #8.6 fallback de reglas (Capa 5)."""
from __future__ import annotations

from edl_agent.selection import apply_s_checks, build_selected


def _cand(cid, src, kind, kp_speed=0.5, motion_bg=0.1, sharpness=0.8,
          bbox=(0.3, 0.1, 0.7, 0.9), multi_subject=False, score_cv=0.5,
          admits_slots=None):
    return {
        "id": cid, "src": src, "kind": kind,
        "kp_speed": kp_speed, "motion_bg": motion_bg, "sharpness": sharpness,
        "subject_bbox": list(bbox), "multi_subject": multi_subject, "score_cv": score_cv,
        "admits_slots": admits_slots if admits_slots is not None else [0, 1, 2, 3],
    }


def _slots(n_develop):
    slots = [{"slot": 0, "role": "hook"}]
    slots += [{"slot": i + 1, "role": "develop"} for i in range(n_develop)]
    slots.append({"slot": n_develop + 1, "role": "close"})
    return {"duration_f": 300, "slots": slots}


def test_s2_drops_unknown_and_duplicate_ids():
    candidates_by_id = {"c1": _cand("c1", "a.mov", "peak")}
    selection = {"selected": [
        {"candidate_id": "c1", "role": "hook", "rank": 1, "exercise": "back squat", "reason": "x"},
        {"candidate_id": "c1", "role": "develop", "rank": 1, "exercise": "back squat", "reason": "dup"},
        {"candidate_id": "ghost", "role": "develop", "rank": 2, "exercise": "back squat", "reason": "x"},
    ]}
    cleaned, warnings = apply_s_checks(selection, candidates_by_id)
    assert [e["candidate_id"] for e in cleaned] == ["c1"]
    assert any("ghost" in w for w in warnings)


def test_s4_moves_mistyped_hook_and_close():
    candidates_by_id = {
        "c1": _cand("c1", "a.mov", "calm"),   # en hook -> debe pasar a close
        "c2": _cand("c2", "b.mov", "peak"),   # en close -> debe pasar a develop
    }
    selection = {"selected": [
        {"candidate_id": "c1", "role": "hook", "rank": 1, "exercise": "x", "reason": "x"},
        {"candidate_id": "c2", "role": "close", "rank": 1, "exercise": "x", "reason": "x"},
    ]}
    cleaned, warnings = apply_s_checks(selection, candidates_by_id)
    roles = {e["candidate_id"]: e["role"] for e in cleaned}
    assert roles["c1"] == "close"
    assert roles["c2"] == "develop"


def test_s3_renumbers_rank_without_gaps():
    candidates_by_id = {"c1": _cand("c1", "a.mov", "peak"), "c2": _cand("c2", "b.mov", "peak")}
    selection = {"selected": [
        {"candidate_id": "c1", "role": "develop", "rank": 5, "exercise": "x", "reason": "x"},
        {"candidate_id": "c2", "role": "develop", "rank": 5, "exercise": "x", "reason": "x"},
    ]}
    cleaned, _ = apply_s_checks(selection, candidates_by_id)
    assert [e["rank"] for e in cleaned] == [1, 2]


def test_build_selected_full_fallback_without_llm():
    candidates_json = {"candidates": [
        _cand("hook0", "a.mov", "peak", kp_speed=0.9, sharpness=0.9),
        _cand("close0", "b.mov", "calm", sharpness=0.9),
        _cand("dev0", "c.mov", "peak", score_cv=0.8),
        _cand("dev1", "d.mov", "peak", score_cv=0.7),
    ]}
    slots_json = _slots(2)
    selected, warnings, fallback_roles = build_selected(candidates_json, slots_json, selection=None)

    roles = {e["role"] for e in selected}
    assert roles == {"hook", "develop", "close"}
    assert set(fallback_roles) == {"hook", "develop", "close"}
    assert sum(1 for e in selected if e["role"] == "develop") == 2


def test_build_selected_partial_fallback_keeps_llm_roles():
    candidates_json = {"candidates": [
        _cand("hook0", "a.mov", "peak"),
        _cand("dev0", "b.mov", "peak"),
        _cand("fallback_close", "c.mov", "calm"),
    ]}
    slots_json = _slots(1)
    selection = {"selected": [
        {"candidate_id": "hook0", "role": "hook", "rank": 1, "exercise": "back squat", "reason": "x"},
        {"candidate_id": "dev0", "role": "develop", "rank": 1, "exercise": "back squat", "reason": "x"},
    ]}
    selected, warnings, fallback_roles = build_selected(candidates_json, slots_json, selection)

    assert fallback_roles == ["close"]
    close_entries = [e for e in selected if e["role"] == "close"]
    assert len(close_entries) == 1
    assert close_entries[0]["candidate_id"] == "fallback_close"
    # hook/develop del LLM no se tocan
    assert any(e["candidate_id"] == "hook0" and e["role"] == "hook" for e in selected)
    assert any(e["candidate_id"] == "dev0" and e["role"] == "develop" for e in selected)


def test_fallback_never_reuses_llm_candidate_id():
    candidates_json = {"candidates": [
        _cand("only_peak", "a.mov", "peak"),
    ]}
    slots_json = _slots(0)
    # LLM ya uso el unico peak admisible para hook; no debe reaparecer en close.
    selection = {"selected": [
        {"candidate_id": "only_peak", "role": "hook", "rank": 1, "exercise": "x", "reason": "x"},
    ]}
    selected, warnings, fallback_roles = build_selected(candidates_json, slots_json, selection)
    assert not any(e["role"] == "close" for e in selected)
    assert "close" not in fallback_roles or all(
        e["candidate_id"] != "only_peak" for e in selected if e["role"] == "close"
    )
