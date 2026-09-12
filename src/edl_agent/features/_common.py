"""Shared config, types, and the `Detection`/`Track` shapes, per #4.2."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

SAMPLE_STRIDE = 3  # 30fps proxy -> sampled at 10fps (#4.2)
IOU_MATCH_THRESHOLD = 0.3
TRACK_MISS_TOLERANCE = 5
BBOX_EMA_ALPHA = 0.3
KP_SPEED_EMA_ALPHA = 0.5
MULTI_SUBJECT_AREA_THRESHOLD = 0.20
# COCO-17: wrists, elbows, hips, knees (#4.2)
ACTION_KEYPOINTS = (9, 10, 7, 8, 11, 12, 13, 14)

FEATURES_CONFIG = {
    "sample_stride": SAMPLE_STRIDE,
    "iou_match_threshold": IOU_MATCH_THRESHOLD,
    "track_miss_tolerance": TRACK_MISS_TOLERANCE,
    "bbox_ema_alpha": BBOX_EMA_ALPHA,
    "kp_speed_ema_alpha": KP_SPEED_EMA_ALPHA,
    "multi_subject_area_threshold": MULTI_SUBJECT_AREA_THRESHOLD,
    "action_keypoints": ACTION_KEYPOINTS,
}


def features_config_sha256() -> str:
    """Hash `FEATURES_CONFIG` to invalidate cached features when params change.

    Returns:
        SHA-256 hex digest of the sorted `FEATURES_CONFIG` items' repr.
    """
    return hashlib.sha256(repr(sorted(FEATURES_CONFIG.items())).encode()).hexdigest()


@dataclass
class Detection:
    """A single pose detection in one frame: bbox plus COCO-17 keypoints."""

    bbox: tuple[float, float, float, float]  # x0,y0,x1,y1, normalized to 0-1
    keypoints: np.ndarray  # (17,3): x,y normalized, plus confidence


Detector = Callable[[np.ndarray], list["Detection"]]


@dataclass
class Track:
    """A sequence of `Detection`s for the same subject across samples (by index)."""

    track_id: int
    samples: dict[int, Detection] = field(default_factory=dict)


def _area(bbox: tuple[float, float, float, float]) -> float:
    x0, y0, x1, y1 = bbox
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)
