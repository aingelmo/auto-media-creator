"""#4.1 Audio -> slots.json. Beats sinteticos (sin fichero de audio real)."""

from __future__ import annotations

import itertools

import pytest

from edl_agent.slots import FRAME_RATE, UNIFORM_GRID_S, build_slots


def _periodic_beats(bpm: float, duration_s: float) -> list[float]:
    step = 60.0 / bpm
    beats = []
    t = 0.0
    while t < duration_s:
        beats.append(t)
        t += step
    return beats


@pytest.mark.parametrize(
    ("bpm", "expected_beats_per_slot"), [(60, 1), (90, 2), (128, 3), (175, 3)]
)
def test_beats_per_slot_formula(bpm, expected_beats_per_slot) -> None:
    duration_s = 20.0
    beats = _periodic_beats(bpm, duration_s)
    result = build_slots(duration_s, bpm, beats, confident=True)
    assert result["beats_per_slot"] == expected_beats_per_slot


@pytest.mark.parametrize("bpm", [60, 90, 128, 175])
def test_slot_invariants(bpm) -> None:
    duration_s = 25.0
    beats = _periodic_beats(bpm, duration_s)
    result = build_slots(duration_s, bpm, beats, confident=True)
    slots = result["slots"]

    assert slots[0]["start_f"] == 0
    assert slots[-1]["end_f"] == result["duration_f"]
    for a, b in itertools.pairwise(slots):
        assert a["end_f"] == b["start_f"]
    for s in slots:
        assert s["end_f"] - s["start_f"] >= 30
        assert s["beats_rel_f"][0] == 0
    assert slots[0]["role"] == "hook"
    assert slots[-1]["role"] == "close"
    assert all(s["role"] == "develop" for s in slots[1:-1])


def test_uniform_grid_when_not_confident() -> None:
    duration_s = 20.0
    result = build_slots(duration_s, tempo_bpm=0.0, beats_s=[], confident=False)
    assert result["beats_per_slot"] == 2
    slots = result["slots"]
    for s in slots[:-1]:
        assert s["end_f"] - s["start_f"] == 48  # 1.6s a 30fps
    assert slots[0]["beats_rel_f"] == [0, 24]


def test_two_slots_minimum_roles() -> None:
    # duracion corta con solo 2 grupos de beats: hook+close, sin develop.
    result = build_slots(
        duration_s=2.0, tempo_bpm=60.0, beats_s=[0.0, 1.0], confident=True
    )
    slots = result["slots"]
    assert len(slots) == 2
    assert slots[0]["role"] == "hook"
    assert slots[1]["role"] == "close"


def test_trailing_gap_falls_back_to_uniform_grid() -> None:
    # Beats detected only for the first ~7s of a 15s clip (rhythmic section
    # ends early); the trailing gap must be subdivided, not left as one slot.
    duration_s = 15.0
    beats = _periodic_beats(120, 7.3)
    result = build_slots(duration_s, tempo_bpm=120.0, beats_s=beats, confident=True)
    slots = result["slots"]
    max_slot_s = max(s["end_f"] - s["start_f"] for s in slots) / FRAME_RATE
    assert max_slot_s <= UNIFORM_GRID_S + 0.1


def test_single_slot_is_error() -> None:
    with pytest.raises(ValueError):
        build_slots(duration_s=0.5, tempo_bpm=60.0, beats_s=[0.0], confident=True)
