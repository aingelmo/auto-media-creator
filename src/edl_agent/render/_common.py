"""Shared constants and helpers used across the render package."""

from __future__ import annotations

import re

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


# Piecewise speed ramp in output frames (#6.3): 1.0x until `t_a` source
# seconds, `s`x for `n` output frames (until `t_b` source seconds), then
# 1.0x again. `T` is input time after `-ss`, which starts at 0. Single
# quotes keep the commas out of the filtergraph parser.
RAMP_SETPTS_TEMPLATE = (
    "'if(lt(T,{t_a}),PTS,if(lt(T,{t_b}),({t_a}+(T-{t_a})/{s})/TB,"
    "({t_a}+{n}/30+(T-{t_b}))/TB))'"
)


def setpts_expr(clip: dict) -> str:
    """`setpts=` value for a clip: `PTS/{speed}` or the ramp expression."""
    if clip["effect"] != "ramp":
        return f"PTS/{clip['speed']}"
    p = clip["effect_params"]
    s, n = p["ramp_speed"], p["ramp_frames"]
    t_a = p["ramp_start_f"] / 30
    t_b = t_a + n / 30 * s
    return RAMP_SETPTS_TEMPLATE.format(t_a=t_a, t_b=t_b, s=s, n=n)


# Hook text (#6.6): white, black-bordered, centred, fades in over `fade`
# frames at 0 and out over `fade` frames ending at `end`. `n` is the frame
# counter after `fps=30`, i.e. the segment frame index. `expansion=none`
# makes `%` literal. Applied after `color_fix` so the white isn't tinted.
HOOK_TEXT_FILTER_TEMPLATE = (
    "drawtext=fontfile='{font}':expansion=none:text={text}:fontsize={size}:"
    "fontcolor=white:borderw={border}:bordercolor=black@0.6:"
    "x=(w-text_w)/2:y={y}:"
    "alpha='if(lt(n,{fade}),n/{fade},if(lt(n,{end}-{fade}),1,"
    "if(lt(n,{end}),({end}-n)/{fade},0)))',"
)


def _drawtext_escape(text: str) -> str:
    r"""Escape `text` for an unquoted `drawtext=text=` value.

    ffmpeg parses it twice: the option parser (`:` separator, `\\` escapes,
    `'` quotes) and, before that, the filtergraph parser (`,;[]` terminators,
    same escapes/quotes). Inside single quotes nothing is escaped, so the
    value stays unquoted and every special char is backslashed at both
    levels.
    """
    s = re.sub(r"([\\:'])", r"\\\1", text)
    return re.sub(r"([\\',;\[\]])", r"\\\1", s)


def hook_text_filter(clip: dict, target: dict) -> str:
    """Hook-text `drawtext` filter (#6.6), trailing comma included; "" if absent."""
    p = clip.get("effect_params", {})
    if not p.get("text"):
        return ""
    scale = target["w"] / 1080
    return HOOK_TEXT_FILTER_TEMPLATE.format(
        font=p["font"],
        text=_drawtext_escape(p["text"]),
        size=round(p["font_size"] * scale),
        border=max(2, round(4 * scale)),
        y=round(p["text_y"] * target["h"]),
        fade=p["fade_frames"],
        end=p["text_frames"],
    )
