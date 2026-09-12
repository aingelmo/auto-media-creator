"""Orchestrate the full #4.2 pipeline over an already-generated proxy."""

from __future__ import annotations

import cv2
import numpy as np

from ._common import (
    BBOX_EMA_ALPHA,
    MULTI_SUBJECT_AREA_THRESHOLD,
    SAMPLE_STRIDE,
    Detector,
    _area,
    features_config_sha256,
)
from .series import motion_series, normalize_p5_95, sharpness_series
from .tracking import principal_track, track_iou, track_kp_speeds


def _read_samples(path: str, stride: int) -> list[np.ndarray]:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        msg = f"cannot open {path}"
        raise RuntimeError(msg)
    frames = []
    idx = 0
    ok, frame = cap.read()
    while ok:
        if idx % stride == 0:
            frames.append(frame)
        idx += 1
        ok, frame = cap.read()
    cap.release()
    return frames


def extract_features(
    proxy_path: str,
    detector: Detector,
    stride: int = SAMPLE_STRIDE,
    source_fps: float = 30.0,
) -> dict:
    """Orchestrate the full #4.2 pipeline over an already-generated proxy.

    `detector` isolates the pose model so the rest of the logic can be
    tested without a real YOLO model.

    Args:
        proxy_path: Path to the proxy video to read frames from.
        detector: Callable that takes a BGR frame (`np.ndarray`) and
            returns a list of `Detection`s.
        stride: Sample every `stride`-th frame. Defaults to `SAMPLE_STRIDE`
            (3, i.e. 10fps from a 30fps proxy).
        source_fps: Frame rate of `proxy_path`, used to convert sample
            indices to seconds. Defaults to 30.0.

    Returns:
        Feature series dict with keys:
        - `t_s` (list[float]): sample timestamps, in seconds.
        - `subject_bbox` (list[tuple | None]): principal subject bbox
          `(x0, y0, x1, y1)`, normalized, per sample (EMA-smoothed); `None`
          where untracked.
        - `subject_visible` (list[bool]): whether the principal subject was
          tracked at each sample.
        - `kp_speed` (list[float]): principal subject's EMA action speed,
          normalized to [0, 1] via 5th/95th percentile clipping.
        - `motion_bg` (list[float]): background motion, normalized the same
          way.
        - `motion` (list[float]): whole-frame motion (diagnostic),
          normalized the same way.
        - `sharpness` (list[float]): subject-region sharpness, normalized
          the same way.
        - `multi_subject` (list[bool]): whether >=2 large detections
          coexist at that sample.
        - `n_tracks` (int): total number of tracks created by `track_iou`.
        - `features_config_sha256` (str): see `features_config_sha256`.

    Raises:
        RuntimeError: If `proxy_path` cannot be opened, or no frames are
            read from it.
    """
    frames = _read_samples(proxy_path, stride)
    if not frames:
        msg = f"no frames read from {proxy_path}"
        raise RuntimeError(msg)
    n = len(frames)

    detections = [detector(f) for f in frames]
    tracks = track_iou(detections)
    speeds = track_kp_speeds(tracks)
    principal_id = principal_track(tracks, speeds) if tracks else None

    subject_bbox: list[tuple | None] = [None] * n
    subject_visible = [False] * n
    kp_speed_raw = np.zeros(n)
    if principal_id is not None:
        track = next(t for t in tracks if t.track_id == principal_id)
        ema_bbox = None
        for i in sorted(track.samples):
            bbox = track.samples[i].bbox
            ema_bbox = (
                bbox
                if ema_bbox is None
                else tuple(
                    BBOX_EMA_ALPHA * b + (1 - BBOX_EMA_ALPHA) * e
                    for b, e in zip(bbox, ema_bbox, strict=False)
                )
            )
            subject_bbox[i] = ema_bbox
            subject_visible[i] = True
            kp_speed_raw[i] = speeds[principal_id].get(i, 0.0)

    multi_subject = [
        sum(1 for d in dets if _area(d.bbox) > MULTI_SUBJECT_AREA_THRESHOLD) >= 2
        for dets in detections
    ]
    motion_bg_raw, motion_raw = motion_series(frames, detections)
    sharpness_raw = sharpness_series(frames, subject_bbox, subject_visible)

    return {
        "t_s": [i * stride / source_fps for i in range(n)],
        "subject_bbox": subject_bbox,
        "subject_visible": subject_visible,
        "kp_speed": normalize_p5_95(kp_speed_raw).tolist(),
        "motion_bg": normalize_p5_95(motion_bg_raw).tolist(),
        "motion": normalize_p5_95(motion_raw).tolist(),
        "sharpness": normalize_p5_95(sharpness_raw).tolist(),
        "multi_subject": multi_subject,
        "n_tracks": len(tracks),
        "features_config_sha256": features_config_sha256(),
    }
