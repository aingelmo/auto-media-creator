"""`calm` candidate windows: stable runs, per #4.3."""

from __future__ import annotations

from edl_agent.candidates._common import (
    CALM_CENTER_X_TOL,
    CALM_CENTER_Y_TOL,
    CALM_KP_SPEED_MAX,
    CALM_MAX_PER_CLIP,
    CALM_MIN_DURATION_S,
    CALM_MOTION_BG_MAX,
    CALM_SHARPNESS_MIN,
)


def _is_centered(bbox: tuple | None) -> bool:
    if bbox is None:
        return False
    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    return abs(cx - 0.5) <= CALM_CENTER_X_TOL and abs(cy - 0.5) <= CALM_CENTER_Y_TOL


def find_calm_windows(features: dict) -> list[dict]:
    """Find `calm` candidate windows: stable runs, per #4.3.

    A sample is "calm" when action, background motion, sharpness, subject
    visibility, and subject centering are all within thresholds
    simultaneously. Consecutive calm samples form a run; only the
    `CALM_MAX_PER_CLIP` longest runs (at least `CALM_MIN_DURATION_S` long)
    are kept per clip.

    Args:
        features: Feature series for one clip, as returned by
            `features.extract_features`. Keys used here: `t_s`, `kp_speed`,
            `motion_bg`, `sharpness`, `subject_visible`, `subject_bbox`
            (see `peaks.find_peak_windows` and `features.extract_features`
            for their shapes).

    Returns:
        List of calm-window dicts, each with keys:
        - `kind` (str): always `"calm"`.
        - `t_peak` (float): timestamp of the run's midpoint sample, in
          seconds (kept as `t_peak` for shape parity with peak candidates).
        - `window` (list[float]): `[start_s, end_s]` of the run.
    """
    n = len(features["t_s"])
    t_s = features["t_s"]
    runs: list[tuple[int, int]] = []
    start = None
    for i in range(n):
        is_calm = (
            features["kp_speed"][i] <= CALM_KP_SPEED_MAX
            and features["motion_bg"][i] <= CALM_MOTION_BG_MAX
            and features["sharpness"][i] >= CALM_SHARPNESS_MIN
            and features["subject_visible"][i]
            and _is_centered(features["subject_bbox"][i])
        )
        if is_calm and start is None:
            start = i
        elif not is_calm and start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, n - 1))

    runs = [(a, b) for a, b in runs if t_s[b] - t_s[a] >= CALM_MIN_DURATION_S]
    runs.sort(key=lambda ab: t_s[ab[1]] - t_s[ab[0]], reverse=True)
    runs = runs[:CALM_MAX_PER_CLIP]

    out = []
    for a, b in runs:
        center_i = (a + b) // 2
        out.append(
            {"kind": "calm", "t_peak": t_s[center_i], "window": [t_s[a], t_s[b]]}
        )
    return out
