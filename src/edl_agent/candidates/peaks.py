"""`peak` candidate windows: local maxima of `kp_speed`, per #4.3."""

from __future__ import annotations

import numpy as np
from scipy.signal import find_peaks

from ._common import (
    PEAK_MIN_DISTANCE_SAMPLES,
    PEAK_MIN_PROMINENCE,
    PEAK_MOTION_BG_MAX,
    PEAK_WINDOW_MAX_S,
    PEAK_WINDOW_SHARPNESS_TOLERANCE,
    SHARPNESS_MIN,
    edge_margin_s,
)


def find_peak_windows(
    features: dict, clip_duration_s: float, scene_cuts_s: list[float]
) -> list[dict]:
    """Find `peak` candidate windows: local maxima of `kp_speed`, per #4.3.

    Detects local maxima in the `kp_speed` series, discards peaks that fail
    quality gates or fall too close to a clip edge or scene cut, then grows a
    window around each surviving peak.

    Args:
        features: Feature series for one clip, as returned by
            `features.extract_features`. Keys used here:
            - `t_s` (list[float]): sample timestamps in seconds.
            - `kp_speed` (list[float]): normalized action-keypoint speed
              per sample, in [0, 1].
            - `sharpness` (list[float]): normalized Laplacian-variance
              sharpness per sample, in [0, 1].
            - `subject_visible` (list[bool]): whether the principal subject
              was tracked in that sample.
            - `motion_bg` (list[float]): normalized background motion
              (outside subject bboxes) per sample, in [0, 1].
        clip_duration_s: Total duration of the source clip, in seconds.
        scene_cuts_s: Timestamps (seconds) of scene cuts detected in the
            clip.

    Returns:
        List of peak-window dicts, one per surviving local maximum, each
        with keys:
        - `kind` (str): always `"peak"`.
        - `t_peak` (float): timestamp of the peak, in seconds.
        - `window` (list[float]): `[start_s, end_s]` bounds the peak may be
          trimmed to.
        - `index` (int): sample index of the peak within `features["t_s"]`.
    """
    kp_speed = np.asarray(features["kp_speed"])
    t_s = features["t_s"]
    sharpness = features["sharpness"]
    subject_visible = features["subject_visible"]
    motion_bg = features["motion_bg"]

    idxs, _ = find_peaks(
        kp_speed, distance=PEAK_MIN_DISTANCE_SAMPLES, prominence=PEAK_MIN_PROMINENCE
    )
    margin = edge_margin_s(clip_duration_s)

    out = []
    for i in idxs:
        t_peak = t_s[i]
        if (
            sharpness[i] < SHARPNESS_MIN
            or not subject_visible[i]
            or motion_bg[i] > PEAK_MOTION_BG_MAX
        ):
            continue
        if t_peak < margin or (clip_duration_s - t_peak) < margin:
            continue
        if any(abs(t_peak - c) < margin for c in scene_cuts_s):
            continue
        window = _peak_window(features, int(i), scene_cuts_s)
        out.append(
            {"kind": "peak", "t_peak": t_peak, "window": window, "index": int(i)}
        )
    return out


def _crosses_cut(t_a: float, t_b: float, scene_cuts_s: list[float]) -> bool:
    lo, hi = min(t_a, t_b), max(t_a, t_b)
    return any(lo < c <= hi for c in scene_cuts_s)


def _peak_window(features: dict, i: int, scene_cuts_s: list[float]) -> list[float]:
    """Grow a candidate window outward from a peak sample, in both directions.

    A scene cut or loss of subject tracking is a hard boundary and stops the
    window immediately; a short run of low sharpness (motion blur from the
    explosive movement that produced the peak itself) is tolerated without
    stopping the window, but the window boundary never advances past the
    last sharp frame.

    Args:
        features: Feature series for one clip (see `find_peak_windows` for
            the keys used).
        i: Sample index of the peak within `features["t_s"]`.
        scene_cuts_s: Timestamps (seconds) of scene cuts detected in the
            clip.

    Returns:
        `[start_s, end_s]`: the grown window bounds, in seconds.
    """
    t_s = features["t_s"]
    sharpness = features["sharpness"]
    subject_visible = features["subject_visible"]
    t_peak = t_s[i]

    def hard_ok(j: int) -> bool:
        return subject_visible[j] and not _crosses_cut(t_peak, t_s[j], scene_cuts_s)

    def extend(step: int) -> int:
        boundary = i
        j = i
        low_sharpness_streak = 0
        while True:
            nxt = j + step
            if not (0 <= nxt < len(t_s)) or abs(t_s[nxt] - t_peak) > PEAK_WINDOW_MAX_S:
                break
            if not hard_ok(nxt):
                break
            j = nxt
            if sharpness[j] >= SHARPNESS_MIN:
                low_sharpness_streak = 0
                boundary = j
            else:
                low_sharpness_streak += 1
                if low_sharpness_streak > PEAK_WINDOW_SHARPNESS_TOLERANCE:
                    break
        return boundary

    lo = extend(-1)
    hi = extend(1)
    return [t_s[lo], t_s[hi]]
