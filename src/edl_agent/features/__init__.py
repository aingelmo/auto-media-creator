"""Layer 2 - Per-frame local features over proxies (#4.2).

Multi-person tracking plus action series (`kp_speed`, `motion_bg`,
`sharpness`) that feed the `peak`/`calm` candidates of #4.3.

Deliberate simplification: the "principal subject" is chosen once per clip
(the track with the highest Sum(kp_speed*area) over the whole clip), rather
than recomputed per candidate window as #4.2 suggests. For gym footage with
one athlete per clip this gives the same result and avoids a second tracking
pass per candidate.
# ponytail: single subject per clip; recompute per window if sessions appear
# with relays/several athletes alternating who is the focus within one clip.
"""

from __future__ import annotations

from ._common import (
    ACTION_KEYPOINTS,
    FEATURES_CONFIG,
    Detection,
    Detector,
    Track,
    features_config_sha256,
)
from .detector import yolo_pose_detector
from .extract import extract_features
from .io import load_features, save_features
from .scenes import detect_scene_cuts
from .series import normalize_p5_95 as _normalize_p5_95
from .tracking import iou, track_iou

__all__ = [
    "ACTION_KEYPOINTS",
    "FEATURES_CONFIG",
    "Detection",
    "Detector",
    "Track",
    "_normalize_p5_95",
    "detect_scene_cuts",
    "extract_features",
    "features_config_sha256",
    "iou",
    "load_features",
    "save_features",
    "track_iou",
    "yolo_pose_detector",
]
