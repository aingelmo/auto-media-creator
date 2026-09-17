"""#5.7 session wiring: `reel_context` summarizes the final EDL for the
hook-copy prompt."""

from __future__ import annotations

from edl_agent.session.hooks import reel_context


def _candidates_by_id():
    return {
        "c08": {"id": "c08", "kp_speed_abs": 1.5},
        "c11": {"id": "c11", "kp_speed_abs": 0.8},
        "c18": {"id": "c18", "kp_speed_abs": 0.1},
    }


def _edl():
    return {
        "clips": [
            {
                "slot": 0,
                "role": "hook",
                "candidate_id": "c08",
                "in_s": 0.0,
                "out_s": 1.5,
            },
            {
                "slot": 1,
                "role": "develop",
                "candidate_id": "c11",
                "in_s": 1.5,
                "out_s": 4.5,
            },
            {
                "slot": 2,
                "role": "close",
                "candidate_id": "c18",
                "in_s": 4.5,
                "out_s": 6.5,
            },
            {
                "slot": 3,
                "role": "end_card",
                "candidate_id": "end_card",
                "in_s": 6.5,
                "out_s": 8.0,
            },
        ]
    }


def _selection():
    return {
        "selected": [
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
        ],
        "notes": "c09, c10, c12: low velocity",
    }


def test_reel_context_lists_clips_in_timeline_order() -> None:
    context = reel_context(_edl(), _candidates_by_id(), _selection())

    assert "1. hook: wall ball, 1.5s, velocidad 1.50 -- explosive movement" in context
    assert (
        "2. develop: kettlebell swing, 3.0s, velocidad 0.80 -- dynamic motion"
        in context
    )
    assert "3. close: other, 2.0s, velocidad 0.10" in context
    assert "clips: 3 (develop: 1)" in context
    assert "c09, c10, c12: low velocity" in context


def test_reel_context_skips_slots_without_candidate_id() -> None:
    context = reel_context(_edl(), _candidates_by_id(), _selection())

    assert "end_card" not in context


def test_reel_context_omits_notes_when_absent() -> None:
    edl = {"clips": [_edl()["clips"][2]]}
    context = reel_context(edl, _candidates_by_id(), None)

    assert "notas del selector" not in context
    assert "clips: 1 (develop: 0)" in context
