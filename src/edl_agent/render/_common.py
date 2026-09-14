"""Shared constants and helpers used across the render package."""

from __future__ import annotations

FINAL_TARGET = {"w": 1080, "h": 1920}
PREVIEW_TARGET = {"w": 540, "h": 960}

COLOR_ARGS = [
    "-color_primaries",
    "bt709",
    "-color_trc",
    "bt709",
    "-colorspace",
    "bt709",
    "-color_range",
    "tv",
]


class RenderError(RuntimeError):
    """An R1-R6 check failed, or the render itself failed."""


def _video_codec_args(threads: int, preview: bool) -> list[str]:
    crf, preset = ("30", "ultrafast") if preview else ("18", "medium")
    return [
        "-c:v",
        "libx264",
        "-crf",
        crf,
        "-preset",
        preset,
        "-profile:v",
        "high",
        "-pix_fmt",
        "yuv420p",
        "-video_track_timescale",
        "30000",
        "-g",
        "60",
        "-keyint_min",
        "60",
        "-sc_threshold",
        "0",
        "-threads",
        str(threads),
    ]


COLOR_FIX_FILTER_TEMPLATE = (
    "eq=brightness={brightness}:saturation={saturation},"
    "colorcorrect=rl={rl}:bl={bl}:rh={rl}:bh={bl},"
)


def color_fix_filter(clip: dict) -> str:
    """Per-clip colour-match filter (#6.7), trailing comma included; "" if absent."""
    fix = clip.get("color_fix")
    return COLOR_FIX_FILTER_TEMPLATE.format(**fix) if fix else ""
