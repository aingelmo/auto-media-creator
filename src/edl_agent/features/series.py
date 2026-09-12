"""Per-frame motion and sharpness series, plus percentile normalization, #4.2."""

from __future__ import annotations

import cv2
import numpy as np


def normalize_p5_95(values: np.ndarray) -> np.ndarray:
    """Clip-normalize `values` to [0, 1] using the 5th/95th percentile range."""
    values = np.asarray(values, dtype=float)
    if values.size == 0:
        return values
    lo, hi = np.percentile(values, [5, 95])
    if hi - lo < 1e-9:
        return np.zeros_like(values)
    return np.clip((values - lo) / (hi - lo), 0.0, 1.0)


def motion_series(
    frames: list[np.ndarray], detections: list[list]
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


def sharpness_series(
    frames: list[np.ndarray],
    subject_bbox: list[tuple | None],
    subject_visible: list[bool],
) -> np.ndarray:
    """Compute per-frame sharpness, per #4.2.

    Args:
        frames: Sampled BGR frames, in chronological order.
        subject_bbox: Principal subject bbox per frame (see
            `extract.extract_features`), or `None` if untracked at that
            frame.
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
