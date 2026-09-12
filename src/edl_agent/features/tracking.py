"""Multi-person IoU tracking and per-track action speed, per #4.2."""

from __future__ import annotations

import numpy as np

from ._common import (
    ACTION_KEYPOINTS,
    IOU_MATCH_THRESHOLD,
    KP_SPEED_EMA_ALPHA,
    TRACK_MISS_TOLERANCE,
    Detection,
    Track,
    _area,
)


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


def track_kp_speeds(tracks: list[Track]) -> dict[int, dict[int, float]]:
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


def principal_track(
    tracks: list[Track], speeds: dict[int, dict[int, float]]
) -> int | None:
    """Pick the track with the highest Sum(kp_speed*area) over the clip, per #4.2.

    See the module-level note in `features/__init__.py` on the "principal
    subject chosen once per clip" simplification.
    """
    best_id, best_score = None, -1.0
    for tr in tracks:
        score = sum(
            speeds[tr.track_id].get(i, 0.0) * _area(tr.samples[i].bbox)
            for i in tr.samples
        )
        if score > best_score:
            best_score, best_id = score, tr.track_id
    return best_id
