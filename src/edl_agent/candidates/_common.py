"""Shared constants for candidate detection and scoring, per #4.3."""

from __future__ import annotations

FPS = 30
PEAK_MIN_DISTANCE_SAMPLES = 10  # >=1s between peaks at 10fps (#4.3.1)
PEAK_MIN_PROMINENCE = 0.2  # [validate]
SHARPNESS_MIN = 0.35  # [validate]
PEAK_MOTION_BG_MAX = 0.6  # [validate]
PEAK_WINDOW_MAX_S = 6.0
PEAK_WINDOW_MIN_HALF_S = 1.0
# minimum half-window kept around a peak even when a sibling peak is closer
# than that, so a short-slot admission isn't destroyed by neighbor-midpoint
# clamping (see PEAK_NMS_IOU_MAX below for the dedup pass that still removes
# near-identical windows this leaves behind)
PEAK_WINDOW_SHARPNESS_TOLERANCE = 3
# frames of low sharpness tolerated without cutting the window (motion blur
# transient from the explosive movement that produces the peak itself); raise
# if it still cuts windows close to real peaks

PEAK_NMS_IOU_MAX = 0.6  # windows overlapping more than this: keep one (#4.3)
PEAK_MAX_PER_CLIP = 3
PEAK_PHASH_MAX_DISTANCE = 6  # matches verify.py's D0_MAX convention

CALM_MIN_DURATION_S = 2.0
CALM_KP_SPEED_MAX = 0.25
CALM_KP_SPEED_ABS_MAX = 0.25  # body-heights/s; cross-clip comparable, unlike
# the p5-95-normalized CALM_KP_SPEED_MAX above (kept as a fallback gate for
# feature caches predating kp_speed_abs, see candidates/build.py)
CALM_MOTION_BG_MAX = 0.25  # [validate]
CALM_SHARPNESS_MIN = 0.5
CALM_CENTER_X_TOL = 0.2
CALM_CENTER_Y_TOL = 0.25
CALM_GAP_TOLERANCE = 3  # samples of a dropped condition tolerated mid-run,
# mirroring PEAK_WINDOW_SHARPNESS_TOLERANCE's motion-blur-transient idiom
CALM_MAX_PER_CLIP = 3

PEAK_FRAME_OFFSETS_S = (-1.0, -0.4, 0.0, 0.5)
# Widened from (-0.3, 0.0, 0.3): a 0.6s span can't distinguish barbell/
# gymnastics movements that share the same peak posture (clean vs snatch vs
# thruster vs front squat) -- the disambiguating evidence is the bar path
# over more of the rep. Kept within PEAK_WINDOW_MIN_HALF_S so frames.py's
# window clamp doesn't collapse offsets into duplicate timestamps on short
# windows.
PEAK_FRAME_SIDE_PX = 512

MIN_SUBJECT_AREA = 0.02  # frame fraction; below this the subject reads as
# "far away" (#4.3 LLM rejection bucket: "sujeto pequeño"/"plano lejano").
# p5 of subject_bbox areas across existing sessions is ~0.028, so this cuts
# only the bottom few percent.


def edge_margin_s(clip_duration_s: float) -> float:
    """Compute the edge-exclusion margin for a clip, per #4.3.2.

    Args:
        clip_duration_s: Total duration of the source clip, in seconds.

    Returns:
        0.5 seconds if the clip is at least 5 seconds long, otherwise 0.25
        seconds. Peaks and scene cuts closer than this margin to a clip edge
        are discarded, since there is not enough footage on one side to build
        a usable window.
    """
    return 0.5 if clip_duration_s >= 5.0 else 0.25


def bbox_area(bbox: tuple | None) -> float:
    """Fraction of frame area covered by `bbox`, or 1.0 if untracked."""
    if bbox is None:
        return 1.0
    x0, y0, x1, y1 = bbox
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def nearest_index(features: dict, t: float) -> int:
    """Sample index in `features["t_s"]` closest to timestamp `t`."""
    t_s = features["t_s"]
    return min(range(len(t_s)), key=lambda i: abs(t_s[i] - t))


def window_bbox(features: dict, w: dict) -> tuple | None:
    """Subject bbox for window `w` (peak: by `index`; calm: nearest sample)."""
    i = w.get("index")
    if i is None:
        i = nearest_index(features, w["t_peak"])
    return features["subject_bbox"][i]
