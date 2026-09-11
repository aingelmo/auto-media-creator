"""#4.2 Features locales por frame: tracker IoU y series derivadas."""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest

from edl_agent.features import (
    Detection, extract_features, load_features, save_features, track_iou, iou, _normalize_p5_95,
)


def test_iou_full_overlap_is_one():
    assert iou((0, 0, 1, 1), (0, 0, 1, 1)) == pytest.approx(1.0)


def test_iou_no_overlap_is_zero():
    assert iou((0, 0, 0.2, 0.2), (0.5, 0.5, 0.7, 0.7)) == 0.0


def _det(bbox):
    return Detection(bbox=bbox, keypoints=np.zeros((17, 3)))


def test_track_iou_follows_slowly_moving_bbox():
    dets = [[_det((0.1 + 0.01 * i, 0.1, 0.4 + 0.01 * i, 0.6))] for i in range(5)]
    tracks = track_iou(dets)
    assert len(tracks) == 1
    assert set(tracks[0].samples) == {0, 1, 2, 3, 4}


def test_track_iou_survives_a_missed_detection():
    dets = [[_det((0.1, 0.1, 0.4, 0.6))], [], [_det((0.11, 0.1, 0.41, 0.6))]]
    tracks = track_iou(dets)
    assert len(tracks) == 1
    assert set(tracks[0].samples) == {0, 2}


def test_track_iou_drops_track_beyond_miss_tolerance():
    dets = [[_det((0.1, 0.1, 0.4, 0.6))]] + [[]] * 6 + [[_det((0.1, 0.1, 0.4, 0.6))]]
    tracks = track_iou(dets)
    assert len(tracks) == 2  # el hueco supera TRACK_MISS_TOLERANCE=5: nuevo track


def test_track_iou_splits_on_large_jump():
    dets = [[_det((0.0, 0.0, 0.2, 0.2))], [_det((0.8, 0.8, 1.0, 1.0))]]
    tracks = track_iou(dets)
    assert len(tracks) == 2


def test_normalize_p5_95_maps_extremes_near_unit_range():
    out = _normalize_p5_95(np.array([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 100]))
    assert out.min() == pytest.approx(0.0)
    assert out.max() == pytest.approx(1.0)


def test_normalize_p5_95_constant_series_is_zero():
    out = _normalize_p5_95(np.array([1.0, 1.0, 1.0]))
    assert (out == 0.0).all()


def _make_clip(path: Path, w=320, h=240, fps=30, duration=2):
    vf = f"testsrc2=size={w}x{h}:rate={fps}"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", vf, "-t", str(duration),
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path)],
        check=True, capture_output=True, text=True,
    )


def test_extract_features_end_to_end_with_fake_detector(tmp_path):
    clip = tmp_path / "clip.mp4"
    _make_clip(clip, duration=2)

    def fake_detector(frame):
        kp = np.zeros((17, 3))
        kp[:, 2] = 1.0
        return [Detection(bbox=(0.3, 0.1, 0.7, 0.9), keypoints=kp)]

    feats = extract_features(str(clip), fake_detector, stride=3, source_fps=30.0)

    assert len(feats["t_s"]) > 0
    assert feats["n_tracks"] == 1
    assert all(feats["subject_visible"])
    for key in ("kp_speed", "sharpness", "motion_bg", "motion"):
        assert all(0.0 <= v <= 1.0 for v in feats[key])


def test_extract_features_no_detections_leaves_subject_invisible(tmp_path):
    clip = tmp_path / "clip.mp4"
    _make_clip(clip, duration=1)

    feats = extract_features(str(clip), lambda frame: [], stride=3, source_fps=30.0)
    assert feats["n_tracks"] == 0
    assert not any(feats["subject_visible"])
    assert all(b is None for b in feats["subject_bbox"])


def test_save_load_features_roundtrip(tmp_path):
    feats = {
        "t_s": [0.0, 0.1], "kp_speed": [0.1, 0.9], "motion_bg": [0.0, 0.2],
        "motion": [0.0, 0.3], "sharpness": [0.5, 0.6],
        "subject_visible": [True, False], "multi_subject": [False, False],
        "subject_bbox": [(0.1, 0.1, 0.5, 0.5), None],
        "n_tracks": 1, "features_config_sha256": "abc",
    }
    path = tmp_path / "f.parquet"
    save_features(feats, path)
    loaded = load_features(path)

    assert loaded["t_s"] == feats["t_s"]
    assert loaded["subject_bbox"][0] == pytest.approx(feats["subject_bbox"][0])
    assert loaded["subject_bbox"][1] is None
