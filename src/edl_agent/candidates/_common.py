"""Shared constants for candidate detection and scoring, per #4.3."""

from __future__ import annotations

FPS = 30
PEAK_MIN_DISTANCE_SAMPLES = 10  # >=1s between peaks at 10fps (#4.3.1)
PEAK_MIN_PROMINENCE = 0.2  # [validate]
SHARPNESS_MIN = 0.35  # [validate]
PEAK_MOTION_BG_MAX = 0.6  # [validate]
PEAK_WINDOW_MAX_S = 6.0
PEAK_WINDOW_SHARPNESS_TOLERANCE = 3
# frames of low sharpness tolerated without cutting the window (motion blur
# transient from the explosive movement that produces the peak itself); raise
# if it still cuts windows close to real peaks

CALM_MIN_DURATION_S = 2.0
CALM_KP_SPEED_MAX = 0.25
CALM_MOTION_BG_MAX = 0.25  # [validate]
CALM_SHARPNESS_MIN = 0.5
CALM_CENTER_X_TOL = 0.2
CALM_CENTER_Y_TOL = 0.25
CALM_MAX_PER_CLIP = 2

PEAK_FRAME_OFFSETS_S = (-0.3, 0.0, 0.3)
PEAK_FRAME_SIDE_PX = 512


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
