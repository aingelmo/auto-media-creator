"""#4.3 Candidatos peak/calm/image sobre series de features sinteticas."""

from __future__ import annotations

import pytest

from edl_agent.candidates import (
    admits_slots,
    build_image_candidate,
    edge_margin_s,
    find_calm_windows,
    find_peak_windows,
    score_cv,
)


def _flat_features(
    n,
    kp_speed=None,
    sharpness=None,
    motion_bg=None,
    subject_visible=None,
    bbox=(0.4, 0.2, 0.6, 0.8),
    stride_hz=10.0,
):
    t_s = [i / stride_hz for i in range(n)]
    return {
        "t_s": t_s,
        "kp_speed": kp_speed or [0.0] * n,
        "sharpness": sharpness or [0.8] * n,
        "motion_bg": motion_bg or [0.1] * n,
        "subject_visible": subject_visible
        if subject_visible is not None
        else [True] * n,
        "subject_bbox": [bbox] * n,
        "multi_subject": [False] * n,
    }


def test_find_peak_windows_detects_prominent_peak_away_from_edges() -> None:
    n = 100  # 10s a 10Hz
    kp = [0.1] * n
    kp[50] = 1.0
    feats = _flat_features(n, kp_speed=kp)

    peaks = find_peak_windows(feats, clip_duration_s=10.0, scene_cuts_s=[])

    assert len(peaks) == 1
    assert peaks[0]["t_peak"] == pytest.approx(5.0)
    assert peaks[0]["window"][0] < 5.0 < peaks[0]["window"][1]


def test_find_peak_windows_discards_near_scene_cut() -> None:
    n = 100
    kp = [0.1] * n
    kp[50] = 1.0
    feats = _flat_features(n, kp_speed=kp)

    assert find_peak_windows(feats, clip_duration_s=10.0, scene_cuts_s=[5.1]) == []


def test_find_peak_windows_discards_low_sharpness() -> None:
    n = 100
    kp = [0.1] * n
    kp[50] = 1.0
    sharpness = [0.8] * n
    sharpness[50] = 0.1
    feats = _flat_features(n, kp_speed=kp, sharpness=sharpness)

    assert find_peak_windows(feats, clip_duration_s=10.0, scene_cuts_s=[]) == []


def test_find_peak_windows_discards_near_clip_edge() -> None:
    n = 30  # 3s: clip corto -> edge_margin 0.25s
    kp = [0.1] * n
    kp[1] = 1.0  # t=0.1s, dentro del margen
    feats = _flat_features(n, kp_speed=kp)

    assert find_peak_windows(feats, clip_duration_s=3.0, scene_cuts_s=[]) == []


def test_find_calm_windows_picks_longest_two_over_two_seconds() -> None:
    n = 300  # 30s a 10Hz
    kp = [0.9] * n
    for a, b in [(0, 40), (100, 160), (200, 210)]:  # 4s, 6s, 1s
        for i in range(a, b):
            kp[i] = 0.1
    feats = _flat_features(n, kp_speed=kp)

    calm = find_calm_windows(feats)

    assert len(calm) == 2
    durations = sorted(round(c["window"][1] - c["window"][0], 1) for c in calm)
    assert durations == [
        3.9,
        5.9,
    ]  # window = [t_first, t_last] del tramo (n-1 pasos de 0.1s)


def test_find_calm_windows_rejects_uncentered_subject() -> None:
    n = 50
    feats = _flat_features(n, kp_speed=[0.1] * n, bbox=(0.0, 0.0, 0.1, 0.2))
    assert find_calm_windows(feats) == []


def test_edge_margin_short_vs_long_clip() -> None:
    assert edge_margin_s(3.0) == 0.25
    assert edge_margin_s(5.0) == 0.5


def test_admits_slots_filters_by_window_duration() -> None:
    slots = [
        {"slot": 0, "start_f": 0, "end_f": 30},
        {"slot": 1, "start_f": 30, "end_f": 300},
    ]
    assert admits_slots((0.0, 1.5), slots) == [0]
    assert admits_slots((0.0, 12.0), slots) == [0, 1]
    assert admits_slots((0.0, 0.5), slots) == []


def test_score_cv_rewards_action_and_centrality_for_peak() -> None:
    high = score_cv(kp_speed=0.9, sharpness=0.9, bbox=(0.4, 0.0, 0.6, 1.0), kind="peak")
    low = score_cv(kp_speed=0.1, sharpness=0.9, bbox=(0.0, 0.0, 0.2, 1.0), kind="peak")
    assert high > low


def test_score_cv_rewards_stillness_for_calm() -> None:
    still = score_cv(
        kp_speed=0.05, sharpness=0.9, bbox=(0.4, 0.0, 0.6, 1.0), kind="calm"
    )
    moving = score_cv(
        kp_speed=0.9, sharpness=0.9, bbox=(0.4, 0.0, 0.6, 1.0), kind="calm"
    )
    assert still > moving


def test_build_image_candidate_admits_all_slots() -> None:
    slots = [{"slot": 0}, {"slot": 1}, {"slot": 2}]
    cand = build_image_candidate("inputs/img.jpg", "c05", slots, "inputs/img.jpg")

    assert cand["kind"] == "image"
    assert cand["window"] == [0.0, 1e9]
    assert cand["admits_slots"] == [0, 1, 2]
