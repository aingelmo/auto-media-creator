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

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import cv2
import numpy as np

if TYPE_CHECKING:
    from pathlib import Path

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


def iou(
    a: tuple[float, float, float, float], b: tuple[float, float, float, float]
) -> float:
    """Compute intersection-over-union between two normalized bboxes.

    Args:
        a: `(x0, y0, x1, y1)`, normalized to [0, 1].
        b: `(x0, y0, x1, y1)`, normalized to [0, 1].

    Returns:
        IoU in [0, 1]; 0.0 if the union has zero area.
    """
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    union = _area(a) + _area(b) - inter
    return inter / union if union > 0 else 0.0


def track_iou(detections_per_sample: list[list[Detection]]) -> list[Track]:
    """Run a greedy IoU-based multi-object tracker, per #4.2.

    Assigns each detection to the most-overlapping active track (IoU
    >= `IOU_MATCH_THRESHOLD`); a track survives up to
    `TRACK_MISS_TOLERANCE` samples without a match before being dropped.

    Args:
        detections_per_sample: One list of `Detection`s per sampled frame,
            in chronological order.

    Returns:
        All tracks created during the run (including ones that ended
        early), each with its `samples` dict mapping sample index to
        `Detection`.
    """
    tracks: list[Track] = []
    active: dict[int, Track] = {}
    misses: dict[int, int] = {}
    next_id = 0

    for i, dets in enumerate(detections_per_sample):
        unmatched = set(range(len(dets)))
        for tid, tr in list(active.items()):
            last_i = max(tr.samples)
            last_bbox = tr.samples[last_i].bbox
            best_j, best_score = None, 0.0
            for j in unmatched:
                score = iou(last_bbox, dets[j].bbox)
                if score > best_score:
                    best_score, best_j = score, j
            if best_j is not None and best_score >= IOU_MATCH_THRESHOLD:
                tr.samples[i] = dets[best_j]
                misses[tid] = 0
                unmatched.discard(best_j)
            else:
                misses[tid] += 1
                if misses[tid] > TRACK_MISS_TOLERANCE:
                    del active[tid]
        for j in unmatched:
            tr = Track(track_id=next_id, samples={i: dets[j]})
            tracks.append(tr)
            active[next_id] = tr
            misses[next_id] = 0
            next_id += 1
    return tracks


def _track_kp_speeds(tracks: list[Track]) -> dict[int, dict[int, float]]:
    """Compute the EMA speed of `ACTION_KEYPOINTS` per track, per #4.2.

    Normalized by bbox height and robust to tracking gaps (the sample-index
    delta is used as the time step, so a missed sample does not distort the
    velocity estimate).

    Args:
        tracks: Tracks as returned by `track_iou`.

    Returns:
        Mapping `track_id -> {sample_index: ema_speed}`; a track's map only
        has entries from its second sample onward (a speed needs two
        samples).
    """
    result: dict[int, dict[int, float]] = {}
    for tr in tracks:
        idxs = sorted(tr.samples)
        speeds: dict[int, float] = {}
        ema = None
        prev_i = None
        for i in idxs:
            if prev_i is not None:
                gap = i - prev_i
                kp_a, kp_b = tr.samples[prev_i].keypoints, tr.samples[i].keypoints
                dists = [
                    float(np.hypot(kp_b[k, 0] - kp_a[k, 0], kp_b[k, 1] - kp_a[k, 1]))
                    for k in ACTION_KEYPOINTS
                    if kp_a[k, 2] > 0 and kp_b[k, 2] > 0
                ]
                bbox_h = max(tr.samples[i].bbox[3] - tr.samples[i].bbox[1], 1e-6)
                raw = (sum(dists) / len(dists) / bbox_h / gap) if dists else 0.0
                ema = (
                    raw
                    if ema is None
                    else KP_SPEED_EMA_ALPHA * raw + (1 - KP_SPEED_EMA_ALPHA) * ema
                )
                speeds[i] = ema
            prev_i = i
        result[tr.track_id] = speeds
    return result


def _principal_track(
    tracks: list[Track], speeds: dict[int, dict[int, float]]
) -> int | None:
    best_id, best_score = None, -1.0
    for tr in tracks:
        score = sum(
            speeds[tr.track_id].get(i, 0.0) * _area(tr.samples[i].bbox)
            for i in tr.samples
        )
        if score > best_score:
            best_score, best_id = score, tr.track_id
    return best_id


def _normalize_p5_95(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    if values.size == 0:
        return values
    lo, hi = np.percentile(values, [5, 95])
    if hi - lo < 1e-9:
        return np.zeros_like(values)
    return np.clip((values - lo) / (hi - lo), 0.0, 1.0)


def _motion_series(
    frames: list[np.ndarray], detections: list[list[Detection]]
) -> tuple[np.ndarray, np.ndarray]:
    """Compute per-frame motion series, per #4.2.

    Args:
        frames: Sampled BGR frames, in chronological order.
        detections: One list of `Detection`s per frame, aligned with
            `frames`.

    Returns:
        `(motion_bg, motion)`: two arrays of the same length as `frames`.
        `motion_bg` is mean frame-diff magnitude outside all detected
        person bboxes (used for candidate scoring); `motion` is the same
        computed over the whole frame (diagnostic only, not consumed
        downstream).
    """
    n = len(frames)
    motion_bg, motion = np.zeros(n), np.zeros(n)
    prev_gray = None
    for i, frame in enumerate(frames):
        gray = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (5, 5), 0)
        if prev_gray is not None:
            diff = cv2.absdiff(gray, prev_gray).astype(np.float32) / 255.0
            motion[i] = float(diff.mean())
            h, w = diff.shape
            mask = np.ones_like(diff, dtype=bool)
            for d in detections[i]:
                x0, y0, x1, y1 = d.bbox
                mask[int(y0 * h) : int(y1 * h), int(x0 * w) : int(x1 * w)] = False
            motion_bg[i] = float(diff[mask].mean()) if mask.any() else motion[i]
        prev_gray = gray
    if n > 1:
        motion[0], motion_bg[0] = motion[1], motion_bg[1]
    return motion_bg, motion


def _sharpness_series(
    frames: list[np.ndarray],
    subject_bbox: list[tuple | None],
    subject_visible: list[bool],
) -> np.ndarray:
    """Compute per-frame sharpness, per #4.2.

    Args:
        frames: Sampled BGR frames, in chronological order.
        subject_bbox: Principal subject bbox per frame (see
            `extract_features`), or `None` if untracked at that frame.
        subject_visible: Whether the principal subject was tracked at each
            frame, aligned with `frames`.

    Returns:
        Array of the same length as `frames` holding the Laplacian variance
        computed inside the subject bbox (or over the full frame when no
        subject is visible, a reasonable fallback since `subject_visible`
        already excludes those instants from the candidate filters that
        consume this series).
    """
    out = np.zeros(len(frames))
    for i, frame in enumerate(frames):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        roi = gray
        bbox = subject_bbox[i]
        if subject_visible[i] and bbox is not None:
            h, w = gray.shape
            x0, y0, x1, y1 = bbox
            x0i, y0i = int(x0 * w), int(y0 * h)
            x1i, y1i = max(x0i + 1, int(x1 * w)), max(y0i + 1, int(y1 * h))
            roi = gray[y0i:y1i, x0i:x1i]
        out[i] = float(cv2.Laplacian(roi, cv2.CV_64F).var()) if roi.size else 0.0
    return out


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
    speeds = _track_kp_speeds(tracks)
    principal_id = _principal_track(tracks, speeds) if tracks else None

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
    motion_bg_raw, motion_raw = _motion_series(frames, detections)
    sharpness_raw = _sharpness_series(frames, subject_bbox, subject_visible)

    return {
        "t_s": [i * stride / source_fps for i in range(n)],
        "subject_bbox": subject_bbox,
        "subject_visible": subject_visible,
        "kp_speed": _normalize_p5_95(kp_speed_raw).tolist(),
        "motion_bg": _normalize_p5_95(motion_bg_raw).tolist(),
        "motion": _normalize_p5_95(motion_raw).tolist(),
        "sharpness": _normalize_p5_95(sharpness_raw).tolist(),
        "multi_subject": multi_subject,
        "n_tracks": len(tracks),
        "features_config_sha256": features_config_sha256(),
    }


def detect_scene_cuts(proxy_path: str) -> list[float]:
    """Detect scene cuts with PySceneDetect's `ContentDetector`, per #4.2.

    Args:
        proxy_path: Path to the proxy video to scan.

    Returns:
        Timestamps (seconds) of each detected scene cut (i.e. the start
        time of every scene after the first), using PySceneDetect's default
        detection threshold [validate].
    """
    from scenedetect import SceneManager, open_video
    from scenedetect.detectors import ContentDetector

    video = open_video(str(proxy_path))
    manager = SceneManager()
    manager.add_detector(ContentDetector())
    manager.detect_scenes(video)
    scenes = manager.get_scene_list()
    return [start.get_seconds() for start, _ in scenes[1:]]


def yolo_pose_detector(model_path: str = "yolov8n-pose.pt") -> Detector:
    """Build the real pose `Detector`, per #4.2: ultralytics YOLOv8-pose.

    Uses a lazy import so the rest of the module does not depend on
    torch/ultralytics in unit tests.

    Args:
        model_path: Path or model name to load with `ultralytics.YOLO`.
            Defaults to `"yolov8n-pose.pt"`.

    Returns:
        A `Detector` callable: takes a BGR frame and returns a list of
        `Detection`s with bbox and keypoints normalized to the frame's
        width/height. Keypoints are all-zero if the model returns none.
    """
    from ultralytics import YOLO

    model = YOLO(model_path)

    def _detect(frame_bgr: np.ndarray) -> list[Detection]:
        h, w = frame_bgr.shape[:2]
        predictions: Any = model.predict(frame_bgr, verbose=False)
        result = predictions[0]
        dets: list[Detection] = []
        if result.boxes is None:
            return dets
        boxes = result.boxes.xyxy.cpu().numpy()
        kpts = (
            result.keypoints.data.cpu().numpy()
            if result.keypoints is not None
            else None
        )
        for i, box in enumerate(boxes):
            x0, y0, x1, y1 = (float(v) for v in box)
            bbox = (x0 / w, y0 / h, x1 / w, y1 / h)
            if kpts is not None:
                kp = kpts[i].copy()
                kp[:, 0] /= w
                kp[:, 1] /= h
            else:
                kp = np.zeros((17, 3))
            dets.append(Detection(bbox=bbox, keypoints=kp))
        return dets

    return _detect


def save_features(features: dict, path: Path) -> None:
    """Serialize a `features` dict (from `extract_features`) to Parquet.

    Args:
        features: Feature series dict, as returned by `extract_features`.
        path: Output `.parquet` path (parent directory created if
            missing).
    """
    import pandas as pd

    bbox = features["subject_bbox"]
    df = pd.DataFrame(
        {
            "t_s": features["t_s"],
            "kp_speed": features["kp_speed"],
            "motion_bg": features["motion_bg"],
            "motion": features["motion"],
            "sharpness": features["sharpness"],
            "subject_visible": features["subject_visible"],
            "multi_subject": features["multi_subject"],
            "bbox_x0": [b[0] if b else np.nan for b in bbox],
            "bbox_y0": [b[1] if b else np.nan for b in bbox],
            "bbox_x1": [b[2] if b else np.nan for b in bbox],
            "bbox_y1": [b[3] if b else np.nan for b in bbox],
        }
    )
    df.attrs["features_config_sha256"] = features["features_config_sha256"]
    df.attrs["n_tracks"] = features["n_tracks"]
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)


def load_features(path: Path) -> dict:
    """Deserialize the feature dict saved by `save_features`.

    Args:
        path: Input `.parquet` path.

    Returns:
        Feature series dict with keys `t_s`, `kp_speed`, `motion_bg`,
        `motion`, `sharpness`, `subject_visible`, `multi_subject`,
        `subject_bbox` (reconstructed as `(x0, y0, x1, y1)` tuples, or
        `None` where any coordinate was `NaN`). Does not restore
        `features_config_sha256`/`n_tracks` (only used by `save_features`
        for storage metadata, not by downstream consumers of the returned
        dict).
    """
    import pandas as pd

    df = pd.read_parquet(path)
    bbox = [
        None if np.isnan(x0) else (x0, y0, x1, y1)
        for x0, y0, x1, y1 in zip(
            df["bbox_x0"],
            df["bbox_y0"],
            df["bbox_x1"],
            df["bbox_y1"],
            strict=True,
        )
    ]
    return {
        "t_s": df["t_s"].tolist(),
        "kp_speed": df["kp_speed"].tolist(),
        "motion_bg": df["motion_bg"].tolist(),
        "motion": df["motion"].tolist(),
        "sharpness": df["sharpness"].tolist(),
        "subject_visible": df["subject_visible"].tolist(),
        "multi_subject": df["multi_subject"].tolist(),
        "subject_bbox": bbox,
    }
