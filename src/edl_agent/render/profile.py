"""render_profile (#7, #10): everything needed to re-render bit-for-bit."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from edl_agent.render._common import (
    COLOR_FIX_FILTER_TEMPLATE,
    END_CARD_FILTER_TEMPLATE,
    END_CARD_TEXT_TEMPLATE,
    FLASH_FILTER_TEMPLATE,
    HOOK_ASS_TEMPLATE,
    LOGO_FILTER_TEMPLATE,
    PUNCH_FILTER_TEMPLATE,
    RAMP_SETPTS_TEMPLATE,
    SFX_FILTER_TEMPLATE,
    _video_codec_args,
)


def _dpkg_version(package_prefix: str) -> str | None:
    # ponytail: only covers Debian/Ubuntu (dpkg-query); on other distros
    # returns None and zimg_version/libx264_version stay unverified.
    try:
        out = subprocess.run(
            ["dpkg-query", "-W", "-f=${Package} ${Version}\n"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except subprocess.CalledProcessError, FileNotFoundError:
        return None
    for line in out.splitlines():
        pkg, _, version = line.partition(" ")
        if pkg.startswith(package_prefix):
            return version
    return None


def _ffmpeg_version_info() -> dict:
    out = subprocess.run(
        ["ffmpeg", "-version"], check=True, capture_output=True, text=True
    ).stdout
    lines = out.splitlines()
    version = lines[0].split(" ")[2]
    config_line = next(
        (line for line in lines if line.startswith("configuration:")), ""
    )
    configuration = config_line.removeprefix("configuration:").strip()
    return {"ffmpeg_version": version, "ffmpeg_configuration": configuration}


def _file_sha256(path: str | None) -> str | None:
    if not path or not Path(path).is_file():
        return None
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def get_render_profile(
    threads: int = 4,
    tonemap_chain: str = "",
    tonemap_chain_pq: str | None = None,
    hook_text_font: str | None = None,
    brand_sha256: str | None = None,
) -> dict:
    """Describe everything needed to re-render bit-for-bit, per #7/#10.

    Args:
        threads: ffmpeg thread count used for the render.
        tonemap_chain: HDR (HLG/DV84) tonemap filter chain applied to
            proxies/segments during this session.
        tonemap_chain_pq: HDR (PQ) tonemap filter chain, if applicable;
            `None` otherwise.
        hook_text_font: Font file used by the hook text overlay (#6.6), so a
            font change alters `profile_sha256`; `None` if no hook text.
        brand_sha256: Hash of `edl["brand"]` (logo bytes + brand.json
            fields, #6.8), or `None` when the brand layer is off.

    Returns:
        Dict with keys `ffmpeg_version`, `ffmpeg_configuration`,
        `libx264_version`, `zimg_version` (any may be `"unknown"`/`None` if
        undetectable, see `_dpkg_version`), `threads`, `tonemap_chain`,
        `tonemap_chain_pq`, `video_codec_args` (str), the ffmpeg filter
        templates used at render time (`segment_filter_template`,
        `blur_pad_filter_template`, `image_filter_template`, each a format
        string with `{...}` placeholders filled in per-clip;
        `color_fix_filter_template` fills `{color_fix}`, #6.7;
        `ramp_setpts_template` fills `{setpts}` for `effect == "ramp"`;
        `hook_ass_template` is the ASS script skeleton used for the hook
        text overlay, with `hook_text_font`/`hook_text_font_sha256`;
        `punch_filter_template`
        and `flash_filter_template` fill `{fx}` for the cut effects
        (#6.6); `logo_filter_template` and `end_card_filter_template` for
        the brand layer, with `brand_sha256`),
        `audio_codec_args` (str), and `profile_sha256` (str, hash of the
        rest of the dict, for reproducibility checks).
    """
    profile = {
        **_ffmpeg_version_info(),
        "libx264_version": _dpkg_version("libx264") or "unknown",
        "zimg_version": _dpkg_version("libzimg"),
        "threads": threads,
        "tonemap_chain": tonemap_chain,
        "tonemap_chain_pq": tonemap_chain_pq,
        "video_codec_args": " ".join(_video_codec_args(threads, preview=False)),
        "segment_filter_template": (
            "crop={w}:{h}:{x}:{y},setpts={setpts},fps=30,"
            "scale={tw}:{th}:flags=lanczos,{hdr}{color_fix}{text}{fx}{logo}setsar=1,format=yuv420p"
        ),
        "blur_pad_filter_template": (
            "[0:v]setpts={setpts},fps=30,scale='if(gt(iw,ih),-2,{tw})':'if(gt(iw,ih),{tw},-2)':flags=lanczos,{hdr}split[a][b];"
            "[a]scale={tw}:{th}:force_original_aspect_ratio=increase,crop={tw}:{th},boxblur={blur_radius}:{blur_power},eq=brightness={bg_brightness}[bg];"
            "[b]scale={tw}:-2:flags=lanczos[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,{text}{fx}{logo}setsar=1,format=yuv420p[v]"
        ),
        "image_filter_template": (
            "crop={w}:{h}:{x}:{y},scale={ptw}:{pth}:flags=lanczos,"
            "zoompan=z='min(1.0+{zoom_per_frame}*(on-1),{zoom_max})':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={tw}x{th}:fps=30,"
            "{logo}setsar=1,format=yuv420p"
        ),
        "color_fix_filter_template": COLOR_FIX_FILTER_TEMPLATE,
        "ramp_setpts_template": RAMP_SETPTS_TEMPLATE,
        "hook_ass_template": HOOK_ASS_TEMPLATE,
        "hook_text_font": hook_text_font,
        "hook_text_font_sha256": _file_sha256(hook_text_font),
        "punch_filter_template": PUNCH_FILTER_TEMPLATE,
        "flash_filter_template": FLASH_FILTER_TEMPLATE,
        "logo_filter_template": LOGO_FILTER_TEMPLATE,
        "end_card_filter_template": END_CARD_FILTER_TEMPLATE + END_CARD_TEXT_TEMPLATE,
        "brand_sha256": brand_sha256,
        "sfx_filter_template": SFX_FILTER_TEMPLATE,
        "audio_codec_args": "-c:a aac -b:a 192k -ar 48000",
    }
    profile["profile_sha256"] = hashlib.sha256(
        json.dumps(profile, sort_keys=True).encode(),
    ).hexdigest()
    return profile
