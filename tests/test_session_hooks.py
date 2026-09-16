"""#5.7 session wiring: `selection_context` summarizes the selection for the
hook-copy prompt."""

from __future__ import annotations

from edl_agent.session.hooks import selection_context


def _candidates_by_id():
    return {
        "c08": {
            "id": "c08",
            "kind": "peak",
            "kp_speed_abs": 1.5,
            "multi_subject": False,
        },
        "c11": {
            "id": "c11",
            "kind": "peak",
            "kp_speed_abs": 0.8,
            "multi_subject": True,
        },
        "c18": {
            "id": "c18",
            "kind": "calm",
            "kp_speed_abs": 0.1,
            "multi_subject": False,
        },
    }


def _selected():
    return [
        {
            "candidate_id": "c08",
            "role": "hook",
            "exercise": "wall ball",
            "reason": "explosive movement",
        },
        {
            "candidate_id": "c11",
            "role": "develop",
            "exercise": "kettlebell swing",
            "reason": "dynamic motion",
        },
        {"candidate_id": "c18", "role": "close", "exercise": "other"},
    ]


def test_selection_context_lists_roles_and_exercises() -> None:
    context = selection_context(
        _selected(),
        _candidates_by_id(),
        {"duration_f": 450},
        {"notes": "c09, c10, c12: low velocity"},
    )

    assert "hook: wall ball (peak, velocidad 1.50)" in context
    assert "explosive movement" in context
    assert "develop: kettlebell swing (peak, velocidad 0.80)" in context
    assert "close: other (calm, velocidad 0.10)" in context
    assert "grupo: sí" in context
    assert "duración del reel: 15.0s" in context
    assert "c09, c10, c12: low velocity" in context


def test_selection_context_omits_grupo_and_notes_when_absent() -> None:
    selected = [{"candidate_id": "c18", "role": "close", "exercise": "other"}]
    context = selection_context(
        selected, _candidates_by_id(), {"duration_f": 300}, None
    )

    assert "grupo" not in context
    assert "notas del selector" not in context
