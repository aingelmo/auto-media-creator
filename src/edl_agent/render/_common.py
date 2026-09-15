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


# Punch-in (#6.6): 3x pre-scale + zoompan, same trick as Ken Burns so the
# zoom crops on a fine grid. `on` is 1-based; z ramps 1.0 -> zoom over k
# frames then holds (the next cut resets to 1.0 - that is the punch).
PUNCH_FILTER_TEMPLATE = (
    "scale={pw}:{ph}:flags=lanczos,"
    "zoompan=z='1+({zoom}-1)*min(on-1,{k})/{k}':"
    "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={tw}x{th}:fps=30,"
)
# Hook flash (#6.6): full-frame white for `k` frames starting at frame `f`.
FLASH_FILTER_TEMPLATE = "drawbox=c=white:t=fill:enable='between(n,{f},{f}+{k}-1)',"


def cut_fx_filter(clip: dict, target: dict) -> str:
    """Punch-in and/or flash filters (#6.6), trailing comma included; "" if absent."""
    p = clip.get("effect_params", {})
    out = ""
    if p.get("punch_frames"):
        out += PUNCH_FILTER_TEMPLATE.format(
            pw=target["w"] * 3,
            ph=target["h"] * 3,
            zoom=p["punch_zoom"],
            k=p["punch_frames"],
            tw=target["w"],
            th=target["h"],
        )
    if p.get("flash_frames"):
        out += FLASH_FILTER_TEMPLATE.format(f=p["flash_frame"], k=p["flash_frames"])
    return out


# Brand watermark (#6.8): the logo is ffmpeg input `[1:v]`, scaled to `lw` px
# wide, alpha multiplied by `opacity`, bottom-right, raised `bottom` px so it
# clears the Reels caption/UI. Applied after color_fix and hook text.
LOGO_FILTER_TEMPLATE = (
    "[1:v]scale={lw}:-1:flags=lanczos,format=rgba,colorchannelmixer=aa={opacity}[lg];"
    "[v0][lg]overlay=W-w-{inset}:H-h-{bottom}:format=auto"
)

# End card (#6.8): solid `bg` canvas, logo centred above two text lines.
END_CARD_FILTER_TEMPLATE = (
    "[1:v]scale={lw}:-1:flags=lanczos[lg];"
    "[0:v][lg]overlay=(W-w)/2:(H-h)/2-{lift}[v1];"
    "[v1]{handle}{line}fade=t=in:st=0:d=0.25,setsar=1,format=yuv420p[v]"
)
END_CARD_TEXT_TEMPLATE = (
    "drawtext=fontfile='{font}':expansion=none:text={text}:fontsize={size}:"
    "fontcolor={color}:x=(w-text_w)/2:y={y},"
)


def finish_graph(chain: str, logo: dict | None, target: dict) -> str:
    """`-filter_complex` graph: `[0:v]chain` + optional watermark + `setsar/format`.

    `logo` is `edl["brand"]["watermark"]` (`w`, `opacity`, `inset_x`,
    `bottom_frac`, at 1080 wide) or `None`; the logo file must be input 1.
    """
    if not logo:
        return f"[0:v]{chain}setsar=1,format=yuv420p[v]"
    scale = target["w"] / 1080
    overlay = LOGO_FILTER_TEMPLATE.format(
        lw=round(logo["w"] * scale),
        opacity=logo["opacity"],
        inset=round(logo["inset_x"] * scale),
        bottom=round(logo["bottom_frac"] * target["h"]),
    )
    return f"[0:v]{chain.rstrip(',')}[v0];{overlay},setsar=1,format=yuv420p[v]"


def end_card_graph(params: dict, target: dict) -> str:
    """`-filter_complex` graph for an `end_card` clip (input 0 canvas, input 1 logo)."""
    scale = target["w"] / 1080
    ts = round(params["text_size"] * scale)
    lh = round(params["logo_h"] * scale)
    lift = round(ts * 1.5)
    y0 = f"H/2+{lh // 2 - lift}+{ts}"

    def text(key: str, size: int, color: str, y: str) -> str:
        if not params.get(key):
            return ""
        return END_CARD_TEXT_TEMPLATE.format(
            font=params["font"],
            text=_drawtext_escape(params[key]),
            size=size,
            color=color,
            y=y,
        )

    return END_CARD_FILTER_TEMPLATE.format(
        lw=round(params["logo_w"] * scale),
        lift=lift,
        handle=text("handle", ts, params["fg"], y0),
        line=text(
            "line", round(ts * 0.7), f"{params['fg']}@0.8", f"{y0}+{round(ts * 1.4)}"
        ),
    )
