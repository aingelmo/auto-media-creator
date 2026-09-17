"""`calm` candidate windows: stable runs, per #4.3."""

from __future__ import annotations

from edl_agent.candidates._common import (
    CALM_CENTER_X_TOL,
    CALM_CENTER_Y_TOL,
    CALM_GAP_TOLERANCE,
    CALM_KP_SPEED_ABS_MAX,
    CALM_KP_SPEED_MAX,
    CALM_MAX_PER_CLIP,
    CALM_MIN_DURATION_S,
    CALM_MOTION_BG_MAX,
    CALM_SHARPNESS_MIN,
)


def _centrality(bbox: tuple | None) -> float:
    """Score how close `bbox`'s center is to frame center, in [0, 1]."""
    if bbox is None:
        return 0.0
    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    x_frac = min(abs(cx - 0.5) / CALM_CENTER_X_TOL, 1.0)
    y_frac = min(abs(cy - 0.5) / CALM_CENTER_Y_TOL, 1.0)
    return 1.0 - max(x_frac, y_frac)


def _is_calm(features: dict, i: int, kp_speed_key: str, kp_speed_max: float) -> bool:
    return (
        features[kp_speed_key][i] <= kp_speed_max
        and features["motion_bg"][i] <= CALM_MOTION_BG_MAX
        and features["sharpness"][i] >= CALM_SHARPNESS_MIN
        and features["subject_visible"][i]
    )


def _find_runs(
    n: int, is_calm: list[bool], gap_tolerance: int
) -> list[tuple[int, int]]:
    """Group `is_calm` samples into contiguous runs, per #4.3.

    Args:
        n: Number of samples.
        is_calm: Per-sample calm flag.
        gap_tolerance: Number of consecutive non-calm samples tolerated
            mid-run without closing it (a single dropped detection
            shouldn't split an otherwise-stable stretch).

    Returns:
        List of `(start_index, end_index)` runs, inclusive.
    """
    runs: list[tuple[int, int]] = []
    run: tuple[int, int] | None = None  # (start_index, last_calm_index)
    gap = 0
    for i in range(n):
        if is_calm[i]:
            run = (run[0] if run else i, i)
            gap = 0
        elif run is not None:
            gap += 1
            if gap > gap_tolerance:
                runs.append(run)
                run = None
    if run is not None:
        runs.append(run)
    return runs


def find_calm_windows(features: dict) -> list[dict]:
    """Find `calm` candidate windows: stable runs, per #4.3.

    A sample is "calm" when action, background motion, sharpness, and
    subject visibility are all within thresholds simultaneously; up to
    `CALM_GAP_TOLERANCE` consecutive non-calm samples are tolerated without
    splitting a run. Action is gated on `kp_speed_abs` (body-heights/s,
    comparable across clips) when available, falling back to the
    per-clip-normalized `kp_speed` for feature caches that predate it.
    Subject centering is no longer a hard gate (a subject framed on a
    third is still a usable calm shot); it instead weights each run's
    quality score alongside sharpness, used to pick the
    `CALM_MAX_PER_CLIP` best runs. If no run passes the normal gates, the
    single longest run under a relaxed action-only gate is returned instead
    of leaving the clip without any `calm` candidate (see #8.6: `close`
    otherwise falls back to a `peak`).

    Args:
        features: Feature series for one clip, as returned by
            `features.extract_features`. Keys used here: `t_s`, `kp_speed`,
            `kp_speed_abs` (optional), `motion_bg`, `sharpness`,
            `subject_visible`, `subject_bbox` (see `peaks.find_peak_windows`
            and `features.extract_features` for their shapes).

    Returns:
        List of calm-window dicts, each with keys:
        - `kind` (str): always `"calm"`.
        - `t_peak` (float): timestamp of the run's midpoint sample, in
          seconds (kept as `t_peak` for shape parity with peak candidates).
        - `window` (list[float]): `[start_s, end_s]` of the run.
    """
    n = len(features["t_s"])
    t_s = features["t_s"]
    sharpness = features["sharpness"]
    subject_bbox = features["subject_bbox"]

    if "kp_speed_abs" in features:
        kp_speed_key, kp_speed_max = "kp_speed_abs", CALM_KP_SPEED_ABS_MAX
    else:
        kp_speed_key, kp_speed_max = "kp_speed", CALM_KP_SPEED_MAX

    is_calm = [_is_calm(features, i, kp_speed_key, kp_speed_max) for i in range(n)]
    runs = _find_runs(n, is_calm, CALM_GAP_TOLERANCE)
    runs = [(a, b) for a, b in runs if t_s[b] - t_s[a] >= CALM_MIN_DURATION_S]

    if not runs:
        return _relaxed_calm_window(features, kp_speed_key, kp_speed_max)

    def run_score(ab: tuple[int, int]) -> float:
        a, b = ab
        samples = range(a, b + 1)
        avg_sharpness = sum(sharpness[i] for i in samples) / len(samples)
        avg_centrality = sum(_centrality(subject_bbox[i]) for i in samples) / len(
            samples
        )
        return avg_sharpness * (0.5 + 0.5 * avg_centrality)

    runs.sort(key=run_score, reverse=True)
    runs = runs[:CALM_MAX_PER_CLIP]

    out = []
    for a, b in runs:
        center_i = (a + b) // 2
        out.append(
            {"kind": "calm", "t_peak": t_s[center_i], "window": [t_s[a], t_s[b]]}
        )
    return out


def _relaxed_calm_window(
    features: dict, kp_speed_key: str, kp_speed_max: float
) -> list[dict]:
    """Fall back to the single quietest run when no run passes normal gates.

    Drops the motion_bg/sharpness/visibility gates, keeping only the action
    threshold, and returns the longest such run regardless of
    `CALM_MIN_DURATION_S`. A weak `calm` candidate the LLM/planner can still
    reject is better than the clip contributing none at all.
    """
    n = len(features["t_s"])
    t_s = features["t_s"]
    is_calm = [features[kp_speed_key][i] <= kp_speed_max for i in range(n)]
    runs = _find_runs(n, is_calm, CALM_GAP_TOLERANCE)
    if not runs:
        return []
    a, b = max(runs, key=lambda ab: t_s[ab[1]] - t_s[ab[0]])
    center_i = (a + b) // 2
    return [{"kind": "calm", "t_peak": t_s[center_i], "window": [t_s[a], t_s[b]]}]
