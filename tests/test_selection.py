"""#8.1 S-checks y #8.6 fallback de reglas (Capa 5)."""

from __future__ import annotations

from edl_agent.selection import apply_s_checks, build_selected


def _cand(
    cid,
    src,
    kind,
    kp_speed=0.5,
    motion_bg=0.1,
    sharpness=0.8,
    bbox=(0.3, 0.1, 0.7, 0.9),
    multi_subject=False,
    score_cv=0.5,
    admits_slots=None,
):
    return {
        "id": cid,
        "src": src,
        "kind": kind,
        "kp_speed": kp_speed,
        "motion_bg": motion_bg,
        "sharpness": sharpness,
        "subject_bbox": list(bbox),
        "multi_subject": multi_subject,
        "score_cv": score_cv,
        "admits_slots": admits_slots if admits_slots is not None else [0, 1, 2, 3],
    }


def _slots(n_develop):
    slots = [{"slot": 0, "role": "hook"}]
    slots += [{"slot": i + 1, "role": "develop"} for i in range(n_develop)]
    slots.append({"slot": n_develop + 1, "role": "close"})
    return {"duration_f": 300, "slots": slots}


def test_s2_drops_unknown_and_duplicate_ids() -> None:
    candidates_by_id = {"c1": _cand("c1", "a.mov", "peak")}
    selection = {
        "selected": [
            {
                "candidate_id": "c1",
                "role": "hook",
                "rank": 1,
                "exercise": "back squat",
                "reason": "x",
            },
            {
                "candidate_id": "c1",
                "role": "develop",
                "rank": 1,
                "exercise": "back squat",
                "reason": "dup",
            },
            {
                "candidate_id": "ghost",
                "role": "develop",
                "rank": 2,
                "exercise": "back squat",
                "reason": "x",
            },
        ]
    }
    cleaned, warnings = apply_s_checks(selection, candidates_by_id, _slots(1)["slots"])
    assert [e["candidate_id"] for e in cleaned] == ["c1"]
    assert any("ghost" in w for w in warnings)


def test_s4_moves_mistyped_hook_but_trusts_peak_close() -> None:
    candidates_by_id = {
        "c1": _cand("c1", "a.mov", "calm"),  # en hook -> debe pasar a close
        # en close, kind=="peak" ya es el fallback deliberado del prompt
        # (sujeto mas quieto) -> debe respetarse, no moverse a develop.
        "c2": _cand("c2", "b.mov", "peak"),
    }
    selection = {
        "selected": [
            {
                "candidate_id": "c1",
                "role": "hook",
                "rank": 1,
                "exercise": "x",
                "reason": "x",
            },
            {
                "candidate_id": "c2",
                "role": "close",
                "rank": 1,
                "exercise": "x",
                "reason": "x",
            },
        ]
    }
    cleaned, _warnings = apply_s_checks(selection, candidates_by_id, _slots(1)["slots"])
    roles = {e["candidate_id"]: e["role"] for e in cleaned}
    assert roles["c1"] == "close"
    assert roles["c2"] == "close"


def test_s3_renumbers_rank_without_gaps() -> None:
    candidates_by_id = {
        "c1": _cand("c1", "a.mov", "peak"),
        "c2": _cand("c2", "b.mov", "peak"),
    }
    selection = {
        "selected": [
            {
                "candidate_id": "c1",
                "role": "develop",
                "rank": 5,
                "exercise": "x",
                "reason": "x",
            },
            {
                "candidate_id": "c2",
                "role": "develop",
                "rank": 5,
                "exercise": "x",
                "reason": "x",
            },
        ]
    }
    cleaned, _ = apply_s_checks(selection, candidates_by_id, _slots(1)["slots"])
    assert [e["rank"] for e in cleaned] == [1, 2]


def test_s5_drops_role_inadmissible_for_its_slots() -> None:
    # c1 solo admite el slot 3 (close), no el 0 (hook) que el LLM le asigno.
    candidates_by_id = {"c1": _cand("c1", "a.mov", "peak", admits_slots=[3])}
    selection = {
        "selected": [
            {
                "candidate_id": "c1",
                "role": "hook",
                "rank": 1,
                "exercise": "x",
                "reason": "x",
            },
        ]
    }
    cleaned, warnings = apply_s_checks(selection, candidates_by_id, _slots(2)["slots"])
    assert cleaned == []
    assert any("s5_dropped:c1" in w for w in warnings)


def test_build_selected_full_fallback_without_llm() -> None:
    candidates_json = {
        "candidates": [
            _cand("hook0", "a.mov", "peak", kp_speed=0.9, sharpness=0.9),
            _cand("close0", "b.mov", "calm", sharpness=0.9),
            _cand("dev0", "c.mov", "peak", score_cv=0.8),
            _cand("dev1", "d.mov", "peak", score_cv=0.7),
        ]
    }
    slots_json = _slots(2)
    selected, _warnings, fallback_roles = build_selected(
        candidates_json, slots_json, selection=None
    )

    roles = {e["role"] for e in selected}
    assert roles == {"hook", "develop", "close"}
    assert set(fallback_roles) == {"hook", "develop", "close"}
    assert sum(1 for e in selected if e["role"] == "develop") == 2


def test_build_selected_partial_fallback_keeps_llm_roles() -> None:
    candidates_json = {
        "candidates": [
            _cand("hook0", "a.mov", "peak"),
            _cand("dev0", "b.mov", "peak"),
            _cand("fallback_close", "c.mov", "calm"),
        ]
    }
    slots_json = _slots(1)
    selection = {
        "selected": [
            {
                "candidate_id": "hook0",
                "role": "hook",
                "rank": 1,
                "exercise": "back squat",
                "reason": "x",
            },
            {
                "candidate_id": "dev0",
                "role": "develop",
                "rank": 1,
                "exercise": "back squat",
                "reason": "x",
            },
        ]
    }
    selected, _warnings, fallback_roles = build_selected(
        candidates_json, slots_json, selection
    )

    assert fallback_roles == ["close"]
    close_entries = [e for e in selected if e["role"] == "close"]
    assert len(close_entries) == 1
    assert close_entries[0]["candidate_id"] == "fallback_close"
    # hook/develop del LLM no se tocan
    assert any(e["candidate_id"] == "hook0" and e["role"] == "hook" for e in selected)
    assert any(e["candidate_id"] == "dev0" and e["role"] == "develop" for e in selected)


def test_hook_preempts_develop_when_no_other_admissible_candidate() -> None:
    # unico peak que admite el slot hook (0) ya se lo llevo develop; ningun
    # otro candidato admite el slot hook.
    candidates_json = {
        "candidates": [
            _cand("c04", "a.mov", "peak", kp_speed=0.9, admits_slots=[0, 1]),
            _cand("c06", "b.mov", "peak", admits_slots=[1]),
            _cand("close0", "d.mov", "calm", admits_slots=[2]),
        ]
    }
    slots_json = _slots(1)
    selection = {
        "selected": [
            {
                "candidate_id": "c04",
                "role": "develop",
                "rank": 1,
                "exercise": "x",
                "reason": "x",
            },
            {
                "candidate_id": "c06",
                "role": "develop",
                "rank": 2,
                "exercise": "x",
                "reason": "x",
            },
            {
                "candidate_id": "close0",
                "role": "close",
                "rank": 1,
                "exercise": "x",
                "reason": "x",
            },
        ]
    }
    selected, warnings, _fallback_roles = build_selected(
        candidates_json, slots_json, selection
    )

    hook_entries = [e for e in selected if e["role"] == "hook"]
    assert len(hook_entries) == 1
    assert hook_entries[0]["candidate_id"] == "c04"
    assert any("hook_preempted_develop:c04" in w for w in warnings)
    # develop pierde c04 pero se rellena con c06 (unico develop restante).
    develop_ids = {e["candidate_id"] for e in selected if e["role"] == "develop"}
    assert develop_ids == {"c06"}


def test_close_preempts_develop_when_no_other_admissible_candidate() -> None:
    candidates_json = {
        "candidates": [
            _cand("hook0", "a.mov", "peak"),
            _cand("c05", "b.mov", "calm", admits_slots=[1, 2]),
            _cand("dev_extra", "c.mov", "peak", admits_slots=[1]),
        ]
    }
    slots_json = _slots(1)
    selection = {
        "selected": [
            {
                "candidate_id": "hook0",
                "role": "hook",
                "rank": 1,
                "exercise": "x",
                "reason": "x",
            },
            {
                "candidate_id": "c05",
                "role": "develop",
                "rank": 1,
                "exercise": "x",
                "reason": "x",
            },
        ]
    }
    selected, warnings, _fallback_roles = build_selected(
        candidates_json, slots_json, selection
    )

    close_entries = [e for e in selected if e["role"] == "close"]
    assert len(close_entries) == 1
    assert close_entries[0]["candidate_id"] == "c05"
    assert any("close_preempted_develop:c05" in w for w in warnings)
    develop_ids = {e["candidate_id"] for e in selected if e["role"] == "develop"}
    assert develop_ids == {"dev_extra"}


def test_develop_absorbs_preemption_without_backfill_when_pool_empty() -> None:
    # c04 es el unico admisible para hook; se lo lleva de develop y no queda
    # nada para rellenar el slot develop que deja libre.
    candidates_json = {
        "candidates": [
            _cand("c04", "a.mov", "peak", admits_slots=[0, 1]),
            _cand("close0", "b.mov", "calm"),
        ]
    }
    slots_json = _slots(1)
    selection = {
        "selected": [
            {
                "candidate_id": "c04",
                "role": "develop",
                "rank": 1,
                "exercise": "x",
                "reason": "x",
            },
            {
                "candidate_id": "close0",
                "role": "close",
                "rank": 1,
                "exercise": "x",
                "reason": "x",
            },
        ]
    }
    selected, _warnings, fallback_roles = build_selected(
        candidates_json, slots_json, selection
    )

    assert any(e["role"] == "hook" and e["candidate_id"] == "c04" for e in selected)
    assert not any(e["role"] == "develop" for e in selected)
    assert "develop" in fallback_roles  # intento de backfill, pool vacio


def test_no_preemption_when_hook_has_own_admissible_candidate() -> None:
    candidates_json = {
        "candidates": [
            _cand("hook0", "a.mov", "peak", kp_speed=0.9, sharpness=0.9),
            _cand("dev0", "b.mov", "peak"),
            _cand("close0", "c.mov", "calm"),
        ]
    }
    slots_json = _slots(1)
    selected, warnings, _fallback_roles = build_selected(
        candidates_json, slots_json, selection=None
    )

    assert not any("preempted" in w for w in warnings)
    develop_ids = {e["candidate_id"] for e in selected if e["role"] == "develop"}
    assert "dev0" in develop_ids


def test_fallback_never_reuses_llm_candidate_id() -> None:
    candidates_json = {
        "candidates": [
            _cand("only_peak", "a.mov", "peak"),
        ]
    }
    slots_json = _slots(0)
    # LLM ya uso el unico peak admisible para hook; no debe reaparecer en close.
    selection = {
        "selected": [
            {
                "candidate_id": "only_peak",
                "role": "hook",
                "rank": 1,
                "exercise": "x",
                "reason": "x",
            },
        ]
    }
    selected, _warnings, fallback_roles = build_selected(
        candidates_json, slots_json, selection
    )
    assert not any(e["role"] == "close" for e in selected)
    assert "close" not in fallback_roles or all(
        e["candidate_id"] != "only_peak" for e in selected if e["role"] == "close"
    )


def test_fallback_hook_warns_sharpness_cross_clip_when_pool_spans_sources() -> None:
    # W5: el umbral de sharpness admite candidatos de dos `src` distintas;
    # sharpness es relativo al clip, comparar entre clips es informativo.
    candidates_json = {
        "candidates": [
            _cand("hook_a", "a.mov", "peak", kp_speed=0.5, sharpness=0.9),
            _cand("hook_b", "b.mov", "peak", kp_speed=0.9, sharpness=0.6),
            _cand("close0", "c.mov", "calm"),
        ]
    }
    slots_json = _slots(0)
    _selected, warnings, fallback_roles = build_selected(
        candidates_json, slots_json, selection=None
    )
    assert "sharpness_cross_clip" in warnings
    assert "hook" in fallback_roles


def test_fallback_hook_no_warning_when_pool_is_single_source() -> None:
    candidates_json = {
        "candidates": [
            _cand("hook_a", "a.mov", "peak", kp_speed=0.5, sharpness=0.9),
            _cand("hook_b", "a.mov", "peak", kp_speed=0.9, sharpness=0.6),
            _cand("close0", "c.mov", "calm"),
        ]
    }
    slots_json = _slots(0)
    _selected, warnings, _fallback_roles = build_selected(
        candidates_json, slots_json, selection=None
    )
    assert "sharpness_cross_clip" not in warnings
