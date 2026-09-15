"""Shared constants, errors, and #6.1 admission check."""

from __future__ import annotations

FPS = 30


class PlannerError(RuntimeError):
    """A planner invariant was violated, or a role has no admissible candidate.

    See #0, #8.2.
    """


DEFAULT_CONFIG = {
    "hook_ramp": True,  # #6.3: slow the hook to ramp_speed around the peak beat
    "ramp_speed": 0.4,
    "ramp_frames": 12,  # output frames in the slow window, centred on the beat
    "hook_text": True,  # #6.6: burn the selector's `hook_line` into the hook
    "hook_line_override": "",  # operator-typed line; "" => use the selector's
    "hook_text_font": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "hook_text_size": 88,  # px at 1080 wide
    "hook_text_y": 0.28,  # fraction of height, top of the text box (Reels safe zone)
    "hook_text_max_frames": 60,
    "hook_text_fade_frames": 8,
    "peak_beat_index": 1,  # #6.3: peak lands on the slot's 2nd beat by default
    "allow_blur_pad": True,  # #6.4
    "upscale_threshold": 1.3,
    "ken_burns": True,  # #6.6
    "zoom_per_frame": 0.0015,
    "zoom_max": 1.08,
    "blur_radius": 20,
    "blur_power": 2,
    "bg_brightness": -0.1,
    "adjacency_gap_s": 0.25,  # #6.2.3 anti-overlap margin for the same source
    "color_match": True,  # #6.7
    "color_match_strength": 0.7,
}


def admits(window: tuple[float, float], d_f: int, speed: float) -> bool:
    """Check whether a window admits a clip of `d_f` frames at `speed`, per #6.1.

    Args:
        window: `(start_s, end_s)` bounds of the candidate window, in
            seconds.
        d_f: Slot duration, in frames.
        speed: Playback speed multiplier to apply.

    Returns:
        `True` if the window is long enough to hold `d_f` frames at
        `speed` (with a 2-frame safety margin), `False` otherwise.
    """
    need_s = d_f / FPS * speed
    return (window[1] - window[0]) >= need_s + 2 / FPS


def hook_ramp(config: dict) -> dict | None:
    """`{"speed", "frames"}` for the hook's speed ramp, or `None` if disabled."""
    if not config.get("hook_ramp"):
        return None
    return {"speed": config["ramp_speed"], "frames": config["ramp_frames"]}
