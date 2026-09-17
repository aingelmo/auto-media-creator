"""#4.1 Audio -> slots.json. Beats sinteticos (sin fichero de audio real)."""

from __future__ import annotations

import itertools

import numpy as np
import pytest

from edl_agent.slots import (
    FRAME_RATE,
    UNIFORM_GRID_S,
    build_slots,
    correct_octave_error,
)


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


def test_short_hook_merges_forward() -> None:
    # Irregular beat spacing puts the hook's first 3-beat group at frame 28
    # (< MIN_SLOT_FRAMES); the hook has no predecessor to merge into, so it
    # must merge forward into slot 1 instead of surviving as a 28-frame slot.
    beats_s = [0.0, 1 / 30, 15 / 30, 28 / 30, 68 / 30, 108 / 30]
    result = build_slots(
        duration_s=15.0, tempo_bpm=133.9, beats_s=beats_s, confident=True
    )
    slots = result["slots"]
    assert slots[0]["role"] == "hook"
    assert slots[0]["end_f"] - slots[0]["start_f"] >= 30


def test_single_slot_is_error() -> None:
    with pytest.raises(ValueError):
        build_slots(duration_s=0.5, tempo_bpm=60.0, beats_s=[0.0], confident=True)


def _impulse_train(period_frames: int, n_frames: int) -> np.ndarray:
    env = np.zeros(n_frames)
    env[::period_frames] = 1.0
    return env


def test_correct_octave_error_doubles_when_true_tempo_is_faster() -> None:
    # 64 BPM detected, but the onset envelope is periodic at 128 BPM's lag
    # too (a real four-on-the-floor track's backbeat aliasing).
    sr = 22050
    hop_length = 512
    true_bpm = 128.0
    period_frames = round((60.0 / true_bpm) * sr / hop_length)
    onset_env = _impulse_train(period_frames, n_frames=2000)
    beats_s = [i * (60.0 / (true_bpm / 2)) for i in range(10)]

    tempo_bpm, corrected_beats_s = correct_octave_error(
        true_bpm / 2, beats_s, onset_env, sr
    )

    assert tempo_bpm == true_bpm
    assert len(corrected_beats_s) == 2 * len(beats_s) - 1


def test_correct_octave_error_leaves_fast_tempo_unchanged() -> None:
    onset_env = _impulse_train(period_frames=10, n_frames=2000)
    tempo_bpm, beats_s = correct_octave_error(120.0, [0.0, 0.5], onset_env, sr=22050)
    assert tempo_bpm == 120.0
    assert beats_s == [0.0, 0.5]


def test_correct_octave_error_leaves_unconfident_double_unchanged() -> None:
    # Genuinely periodic at 60 BPM only: doubled lag doesn't align with any
    # impulse, so it must not be mistaken for a faster true tempo.
    sr = 22050
    period_frames = round((60.0 / 60.0) * sr / 512)
    onset_env = _impulse_train(period_frames, n_frames=2000)
    tempo_bpm, beats_s = correct_octave_error(60.0, [0.0, 1.0], onset_env, sr)
    assert tempo_bpm == 60.0
    assert beats_s == [0.0, 1.0]
