"""Shared constants and helpers used across the render package."""

from __future__ import annotations

import re
from pathlib import Path

from PIL import ImageFont

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
    # ffmpeg 9's `-color_*` options no longer write the H.264 VUI
    # primaries/transfer (only colorspace survives), so R4 sees
    # `None` for them. The bitstream filter forces all three VUI
    # tags (1/1/1 = bt709) into the stream; `-c:v copy` in concat
    # then preserves them into the reel.
    "-bsf:v",
    (
        "h264_metadata=colour_primaries=1:transfer_characteristics=1"
        ":matrix_coefficients=1"
    ),
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


COLOR_FIX_FILTER_TEMPLATE = "eq=brightness={brightness},"


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


# Hook text (#6.6): a libass `ass=` overlay rather than `drawtext`, so we get
# a thick outline + soft blurred shadow, a pop-in scale animation and native
# multi-line centring, none of which `drawtext` supports. The script's
# PlayRes is fixed at 1080x1920 regardless of the segment's actual render
# target (540x960 preview or 1080x1920 final); libass scales every Style
# value (font size, outline, shadow, position) to the real frame size on its
# own (`ScaledBorderAndShadow: yes`), so preview and final stay proportional
# without any manual scale math here. Applied after `color_fix` so the white
# isn't tinted.
HOOK_ASS_TEMPLATE = (
    "[Script Info]\n"
    "ScriptType: v4.00+\n"
    "PlayResX: 1080\n"
    "PlayResY: 1920\n"
    "WrapStyle: 2\n"
    "ScaledBorderAndShadow: yes\n"
    "\n"
    "[V4+ Styles]\n"
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
    "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
    "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
    "MarginL, MarginR, MarginV, Encoding\n"
    "Style: Hook,{family},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,"
    "&H80000000,0,0,0,0,100,100,-1,0,1,{outline},{shadow},5,0,0,0,1\n"
    "\n"
    "[Events]\n"
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
    "Effect, Text\n"
    "Dialogue: 0,0:00:00.00,{end},Hook,,0,0,0,,{event_text}\n"
)

HOOK_POP_MS = 300  # entrance pop duration; text itself is visible from frame 0


def _ass_escape(text: str) -> str:
    """Strip ASS override-block delimiters (`{`, `}`) and literal backslashes.

    `clean_hook_line` already restricts the line to es-ES text/punctuation,
    so these shouldn't occur in practice; this is a defensive strip, not a
    real escape (unlike `_drawtext_escape`, ASS has no in-text escape for a
    literal brace).
    """
    return re.sub(r"[{}\\]", "", text)


def _ass_timestamp(frames: int) -> str:
    """`H:MM:SS.CC` ASS timestamp for `frames` at 30 fps."""
    cs = round(frames * 100 / 30)
    s, cs = divmod(cs, 100)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


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


# Diegetic sfx mix (#audio §5): per-entry gain, resample to the music's
# format, and delay to the timeline position; `{ramp}` is the slow-mo split
# (see `render.concat._sfx_chain`), "" for non-ramp entries.
SFX_FILTER_TEMPLATE = (
    "{ramp}volume={gain_db}dB,aresample=48000,aformat=channel_layouts=stereo,"
    "adelay={delay_ms}:all=1"
)


def hook_text_filter(clip: dict, out_path: Path) -> str:
    r"""Hook-text `ass` filter (#6.6), trailing comma included; "" if absent.

    Writes the sidecar script to `out_path.with_suffix(".ass")`. `p["text"]`
    already carries a literal `\N` between wrapped lines (see
    `planner.effects.layout_hook_line`) and is already upper-cased.
    """
    p = clip.get("effect_params", {})
    if not p.get("text"):
        return ""
    size = p["font_size"]
    outline = max(3, round(size * 0.065))
    shadow = max(2, round(outline * 0.5))
    family = ImageFont.truetype(p["font"], 10).getname()[0]
    fontsdir = str(Path(p["font"]).parent)
    cy = round(p["text_y"] * 1920)
    fade_ms = round(p["fade_frames"] * 1000 / 30)
    text = r"\N".join(_ass_escape(part) for part in p["text"].split(r"\N"))
    tags = (
        f"\\an5\\pos(540,{cy})\\blur2\\fscx82\\fscy82"
        f"\\t(0,{HOOK_POP_MS},0.5,\\fscx100\\fscy100)\\fad(0,{fade_ms})"
    )
    ass = HOOK_ASS_TEMPLATE.format(
        family=family,
        size=size,
        outline=outline,
        shadow=shadow,
        end=_ass_timestamp(p["text_frames"]),
        event_text="{" + tags + "}" + text,
    )
    ass_path = out_path.with_suffix(".ass")
    ass_path.parent.mkdir(parents=True, exist_ok=True)
    ass_path.write_text(ass, encoding="utf-8")
    # Same double-parser escaping `drawtext` needs (see `_drawtext_escape`):
    # `ass=`'s `filename=`/`fontsdir=` are colon-delimited option values too.
    return (
        f"ass=filename='{_drawtext_escape(str(ass_path))}':"
        f"fontsdir='{_drawtext_escape(fontsdir)}',"
    )


# Punch-in (#6.6): 3x pre-scale + zoompan, same trick as Ken Burns so the
# zoom crops on a fine grid. `on` is 1-based; the cut lands already at `zoom`
# and z eases back down to 1.0 over k frames (snap-in, ease-out punch).
PUNCH_FILTER_TEMPLATE = (
    "scale={pw}:{ph}:flags=lanczos,"
    "zoompan=z='1+({zoom}-1)*(1-min(on-1,{k})/{k})':"
    "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={tw}x{th}:fps=30,"
)
# Hook flash (#6.6): frame `f` peaks full white, decaying linearly back to
# the untouched picture over `k` frames (bloom-and-fade, not a hard cut).
FLASH_FILTER_TEMPLATE = (
    "eq=brightness='if(between(n,{f},{f}+{k}-1),1-(n-{f})/{k},0)':"
    "saturation='if(between(n,{f},{f}+{k}-1),(n-{f})/{k},1)':eval=frame,"
)


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

# End card (#6.8, legacy pre-C0): solid `bg` canvas, logo centred above
# two text lines. Only old EDLs still carry `effect == "end_card"`; the
# planner now burns the C0 sign-off into the close tail instead (outro).
END_CARD_FILTER_TEMPLATE = (
    "[1:v]scale={lw}:-1:flags=lanczos[lg];"
    "[0:v][lg]overlay=(W-w)/2:(H-h)/2-{lift}[v1];"
    "[v1]{handle}{line}fade=t=in:st=0:d=0.25,setsar=1,format=yuv420p[v]"
)
END_CARD_TEXT_TEMPLATE = (
    "drawtext=fontfile='{font}':expansion=none:text={text}:fontsize={size}:"
    "fontcolor={color}:x=(w-text_w)/2:y={y},"
)


# Outro C0 (#6.8): tail-only brand sign-off. `{cur}` is the label
# carrying the main picture (with or without watermark), `{src}` the
# label carrying the logo input. Blur, dim, logo overlay and handle all
# switch on at output frame `{start}`; the logo fades in on its own
# alpha while the blur snaps (a deliberate focus-pull read).
OUTRO_FILTER_TEMPLATE = (
    "[{src}]scale={lw}:-1:flags=lanczos,format=rgba,"
    "fade=t=in:st={fade_st}:d=0.25:alpha=1[ol];"
    "[{cur}]boxblur={blur_radius}:{blur_power}:enable='gte(n,{start})',"
    "eq=brightness={dim}:eval=frame:enable='gte(n,{start})'[v2];"
    "[v2][ol]overlay=(W-w)/2:(H-h)/2-{lift}:enable='gte(n,{start})'[v3];"
    "[v3]{handle}setsar=1,format=yuv420p[v]"
)


def _centered_y(lh: int, lift: int, ts: int) -> str:
    """Drawtext `y` expression centring the logo/handle block (#6.8).

    The offset is folded in Python so the expression carries one
    signed term (`H/2+40`).
    """
    return f"H/2{lh // 2 - lift + ts:+d}"


def finish_graph(
    chain: str,
    logo: dict | None,
    target: dict,
    outro: dict | None = None,
    n_frames: int = 0,
) -> str:
    """`-filter_complex` graph: `[0:v]chain` + watermark/outro + `setsar/format`.

    Args:
        chain: Main video filter chain (trailing comma tolerated).
        logo: `edl["brand"]["watermark"]` (`w`, `opacity`, `inset_x`,
            `bottom_frac`, at 1080 wide) plus an absolute `path`, or
            `None` for no watermark; the logo file must be input 1.
        target: Render target `{"w", "h"}`; px sizes scale from 1080
            wide.
        outro: C0 sign-off params (`outro_*` keys, see
            `planner._apply_outro`: `outro_frames`, `outro_fg`,
            `outro_font`, `outro_handle`, `outro_logo_w`/`outro_logo_h`,
            `outro_text_size`, `outro_blur_radius`/`outro_blur_power`,
            `outro_dim`, all at 1080 wide), or `None` for no sign-off.
        n_frames: Segment output frames; the tail starts at
            `n_frames - outro_frames`. Only read when `outro` is set.

    Returns:
        Filtergraph string ending in `[v]`. The outro blurs/dims only
        the tail (`enable='gte(n,N)'`), fades the logo in via its own
        alpha, and pops the handle; the head of the clip is untouched.
    """
    scale = target["w"] / 1080
    graph = f"[0:v]{chain.rstrip(',')}[v0]"
    cur = "v0"
    if logo and outro is not None:
        graph += ";[1:v]split=2[lgwm][lgout]"
        wm_src, out_src = "lgwm", "lgout"
    else:
        wm_src = out_src = "1:v"
    if logo:
        overlay = LOGO_FILTER_TEMPLATE.format(
            lw=round(logo["w"] * scale),
            opacity=logo["opacity"],
            inset=round(logo["inset_x"] * scale),
            bottom=round(logo["bottom_frac"] * target["h"]),
        )
        # LOGO_FILTER_TEMPLATE hardcodes `[v0]`/`[1:v]`; re-point it at
        # this clip's labels.
        overlay = overlay.replace("[v0]", f"[{cur}]", 1).replace(
            "[1:v]", f"[{wm_src}]", 1
        )
        graph += f";{overlay}[v1]"
        cur = "v1"
    if outro is not None:
        start = n_frames - outro["outro_frames"]
        ts = round(outro["outro_text_size"] * scale)
        lh = round(outro["outro_logo_h"] * scale)
        lift = round(ts * 1.5)
        y0 = _centered_y(lh, lift, ts)
        handle = ""
        if outro.get("outro_handle"):
            handle = END_CARD_TEXT_TEMPLATE.format(
                font=outro["outro_font"],
                text=_drawtext_escape(outro["outro_handle"]),
                size=ts,
                color=outro["outro_fg"],
                y=y0,
            ).rstrip(",")
            # `enable` is a drawtext *option* (colon), not the next
            # filter (comma) — `,enable=` would parse as a filter
            # named `enable` and fail the graph.
            handle += f":enable='gte(n,{start})',"
        graph += ";" + OUTRO_FILTER_TEMPLATE.format(
            src=out_src,
            cur=cur,
            lw=round(outro["outro_logo_w"] * scale),
            fade_st=start / 30,
            blur_radius=max(2, round(outro["outro_blur_radius"] * scale)),
            blur_power=outro["outro_blur_power"],
            dim=outro["outro_dim"],
            lift=lift,
            start=start,
            handle=handle,
        )
    else:
        graph += f";[{cur}]setsar=1,format=yuv420p[v]"
    return graph


def end_card_graph(params: dict, target: dict) -> str:
    """Build the `-filter_complex` graph for a legacy `end_card` clip (#6.8).

    Only old EDLs still carry `effect == "end_card"` (flat `bg` canvas
    as input 0, logo PNG as input 1); the planner now burns the C0
    sign-off into the close tail instead (see `finish_graph` outro).

    Args:
        params: `clip["effect_params"]` with `bg`, `fg`, `font`,
            `handle`, `line`, `logo_w`, `logo_h`, `text_size` (all at
            1080 wide).
        target: Render target `{"w", "h"}` (`FINAL_TARGET` 1080x1920
            or `PREVIEW_TARGET` 540x960); all px sizes scale from 1080
            wide.

    Returns:
        Filtergraph string ending in `[v]`, with a 0.25s fade-in and
        no exit fade.
    """
    scale = target["w"] / 1080
    ts = round(params["text_size"] * scale)
    lh = round(params["logo_h"] * scale)
    lift = round(ts * 1.5)
    y0 = _centered_y(lh, lift, ts)

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
