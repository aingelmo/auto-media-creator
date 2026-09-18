"""Shared constants, errors, and #6.1 admission check."""

from __future__ import annotations

from pathlib import Path

FPS = 30

# Bundled hook-text font (OFL, ships in src/edl_agent/assets/fonts).
FONTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"


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
    "hook_text_font": str(FONTS_DIR / "Montserrat-ExtraBold.ttf"),
    "hook_text_size": 160,  # px at 1080 wide, before wrap/shrink (~8.3% of 1920 tall)
    "hook_text_y": 0.20,  # fraction of height, CENTRE of the text block (safe zone)
    "hook_text_max_frames": 90,  # 3s hold when the hook slot is long enough
    "hook_text_fade_frames": 6,  # exit-only fade (~200ms); entrance is a pop
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
    "brand": True,  # #6.8: logo watermark on every clip (needs edl["brand"])
    "logo_w": 160,  # px at 1080 wide
    "logo_opacity": 0.6,
    "logo_inset_x": 48,
    "logo_bottom_frac": 0.177,  # offset as fraction of height (clears Reels UI)
    "end_card": True,  # #6.8: brand card taking the last frames of the close slot
    "end_card_frames": 45,
    "end_card_logo_w": 480,
    "end_card_text_size": 48,
    "punch_in": False,  # #6.6: punch_zoom->1.0 over punch_frames on develop cut
    # off by default; enabled from the render-stage preview pause once the
    # operator has watched the low-res reel
    "punch_frames": 5,
    "punch_zoom": 1.06,
    "punch_every": 2,  # punch only every Nth develop cut (1 = every cut)
    "hook_flash": True,  # #6.6: white flash on the hook's peak beat
    "flash_frames": 6,
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
