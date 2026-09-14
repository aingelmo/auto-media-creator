"""Segments (#10.1-10.3, #9): render each clip to its own video file."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from edl_agent.render._common import (
    COLOR_ARGS,
    FINAL_TARGET,
    PREVIEW_TARGET,
    _video_codec_args,
    color_fix_filter,
    setpts_expr,
)
from edl_agent.render.crop import crop_to_px

if TYPE_CHECKING:
    from pathlib import Path


def _hdr_prefix(hdr: str, tonemap_chain: str) -> str:
    return f"{tonemap_chain}," if hdr in ("hlg", "dv84") and tonemap_chain else ""


def render_video_segment(
    clip: dict,
    src_path: str,
    crop_px: dict,
    out_path: Path,
    threads: int,
    tonemap_chain: str,
    preview: bool = False,
) -> None:
    """Render one video segment (`crop` or `blur_pad` layout) to `out_path`.

    Args:
        clip: Clip dict, as produced by `planner.build_clips`. Reads
            `n_frames`, `speed`, `in_s`, `out_s`, `hdr`, `layout`, `effect`
            and `effect_params` (`blur_radius`, `blur_power`,
            `bg_brightness` for `blur_pad`; `ramp_*` for `effect == "ramp"`,
            see `_common.setpts_expr`).
        src_path: Path to the source video (proxy if `preview`, original
            otherwise).
        crop_px: Pixel crop rect `{x, y, w, h}`, as returned by
            `crop_to_px`.
        out_path: Output segment path (parent directory created if
            missing).
        threads: ffmpeg thread count.
        tonemap_chain: HDR (HLG/DV84) tonemap filter chain; ignored when
            `preview` is `True` (see note below).
        preview: If `True`, render at `PREVIEW_TARGET` resolution;
            otherwise at `FINAL_TARGET`. Defaults to `False`.

    Raises:
        subprocess.CalledProcessError: If the ffmpeg invocation fails.
    """
    target = PREVIEW_TARGET if preview else FINAL_TARGET
    n_frames = clip["n_frames"]
    t_safety = clip["out_s"] - clip["in_s"] + 0.5
    setpts = setpts_expr(clip)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # The proxy (source of the preview) already comes out of build_proxy
    # tonemapped to bt709 SDR (#3.2); reapplying the chain here would
    # reinterpret those SDR pixels as HLG again and darken/desaturate the
    # preview.
    hdr_prefix = "" if preview else _hdr_prefix(clip["hdr"], tonemap_chain)
    color_fix = color_fix_filter(clip)

    if clip["layout"] == "crop":
        vf = (
            f"crop={crop_px['w']}:{crop_px['h']}:{crop_px['x']}:{crop_px['y']},"
            f"setpts={setpts},fps=30,"
            f"scale={target['w']}:{target['h']}:flags=lanczos,"
            f"{hdr_prefix}{color_fix}setsar=1,format=yuv420p"
        )
        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            str(clip["in_s"]),
            "-t",
            str(t_safety),
            "-i",
            src_path,
            "-vf",
            vf,
            "-fps_mode",
            "cfr",
            "-frames:v",
            str(n_frames),
            *COLOR_ARGS,
            "-an",
            *_video_codec_args(threads, preview),
            str(out_path),
        ]
    else:  # blur_pad
        params = clip["effect_params"]
        filter_complex = (
            f"[0:v]setpts={setpts},fps=30,"
            f"scale='if(gt(iw,ih),-2,{target['w']})':'if(gt(iw,ih),{target['w']},-2)':flags=lanczos,"
            f"{hdr_prefix}{color_fix}split[a][b];"
            f"[a]scale={target['w']}:{target['h']}:force_original_aspect_ratio=increase,"
            f"crop={target['w']}:{target['h']},"
            f"boxblur={params['blur_radius']}:{params['blur_power']},"
            f"eq=brightness={params['bg_brightness']}[bg];"
            f"[b]scale={target['w']}:-2:flags=lanczos[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,format=yuv420p[v]"
        )
        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            str(clip["in_s"]),
            "-t",
            str(t_safety),
            "-i",
            src_path,
            "-filter_complex",
            filter_complex,
            "-map",
            "[v]",
            "-fps_mode",
            "cfr",
            "-frames:v",
            str(n_frames),
            *COLOR_ARGS,
            "-an",
            *_video_codec_args(threads, preview),
            str(out_path),
        ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def render_image_segment(
    clip: dict,
    image_path: str,
    crop_px: dict,
    out_path: Path,
    threads: int,
    preview: bool = False,
) -> None:
    """Render one image segment (Ken Burns or static crop) to `out_path`.

    Args:
        clip: Clip dict, as produced by `planner.build_clips`. Reads
            `n_frames`, `effect` (`"kenburns"` or `"none"`), and, for Ken
            Burns, `effect_params` (dict with `zoom_per_frame`,
            `zoom_max`).
        image_path: Path to the normalized source image.
        crop_px: Pixel crop rect `{x, y, w, h}`, as returned by
            `crop_to_px`.
        out_path: Output segment path (parent directory created if
            missing).
        threads: ffmpeg thread count.
        preview: If `True`, render at `PREVIEW_TARGET` resolution;
            otherwise at `FINAL_TARGET`. Defaults to `False`.

    Raises:
        subprocess.CalledProcessError: If the ffmpeg invocation fails.
    """
    target = PREVIEW_TARGET if preview else FINAL_TARGET
    n_frames = clip["n_frames"]
    color_fix = color_fix_filter(clip)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if clip["effect"] == "kenburns":
        params = clip["effect_params"]
        prescale_w, prescale_h = target["w"] * 3, target["h"] * 3
        vf = (
            f"crop={crop_px['w']}:{crop_px['h']}:{crop_px['x']}:{crop_px['y']},"
            f"scale={prescale_w}:{prescale_h}:flags=lanczos,"
            f"zoompan=z='min(1.0+{params['zoom_per_frame']}*(on-1),{params['zoom_max']})':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={target['w']}x{target['h']}:fps=30,"
            f"{color_fix}setsar=1,format=yuv420p"
        )
    else:
        vf = (
            f"crop={crop_px['w']}:{crop_px['h']}:{crop_px['x']}:{crop_px['y']},"
            f"scale={target['w']}:{target['h']}:flags=lanczos,{color_fix}setsar=1,format=yuv420p"
        )
    cmd = [
        "ffmpeg",
        "-y",
        "-framerate",
        "30",
        "-loop",
        "1",
        "-i",
        image_path,
        "-vf",
        vf,
        "-fps_mode",
        "cfr",
        "-frames:v",
        str(n_frames),
        *COLOR_ARGS,
        "-an",
        *_video_codec_args(threads, preview),
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def _proxy_wh(proxy_path: Path) -> tuple[int, int]:
    from edl_agent.ingest import _video_stream, ffprobe

    stream = _video_stream(ffprobe(proxy_path))
    return int(stream["width"]), int(stream["height"])


def _src_path_and_dims(
    clip: dict,
    sources_by_src: dict,
    session_dir: Path,
    preview: bool,
) -> tuple[str, int, int]:
    if clip["type"] == "image":
        normalized = session_dir / sources_by_src[clip["src"]]["normalized"]
        return str(normalized), clip["src_w"], clip["src_h"]
    if preview:
        source = sources_by_src[clip["src"]]
        proxy = session_dir / source["proxy"]
        return (str(proxy), *_proxy_wh(proxy))
    return str(session_dir / clip["src"]), clip["src_w"], clip["src_h"]


def render_segment(
    clip: dict,
    sources_by_src: dict,
    session_dir: Path,
    out_dir: Path,
    threads: int,
    tonemap_chain: str,
    preview: bool = False,
) -> Path:
    """Render one clip (video or image), delegating to the matching renderer.

    Args:
        clip: Clip dict, as produced by `planner.build_clips`.
        sources_by_src: Mapping `src -> source dict` (from
            `manifest.json["sources"]`).
        session_dir: Session root directory, used to resolve relative
            source/proxy paths.
        out_dir: Directory to write the rendered segment to.
        threads: ffmpeg thread count.
        tonemap_chain: HDR (HLG/DV84) tonemap filter chain.
        preview: If `True`, render at preview resolution using the proxy
            (recomputing the crop over the proxy's own dimensions);
            otherwise render at final resolution using the original
            source. Defaults to `False`.

    Returns:
        Path to the rendered segment, `out_dir / f"seg_{clip['slot']:02d}.mp4"`.

    Raises:
        subprocess.CalledProcessError: If the underlying ffmpeg invocation
            fails.
    """
    src_path, w, h = _src_path_and_dims(clip, sources_by_src, session_dir, preview)
    out_path = out_dir / f"seg_{clip['slot']:02d}.mp4"
    crop_px = (
        crop_to_px(clip["crop"], w, h, clip["layout"]) if preview else clip["crop_px"]
    )

    if clip["type"] == "image":
        render_image_segment(
            clip, src_path, crop_px, out_path, threads, preview=preview
        )
    else:
        render_video_segment(
            clip, src_path, crop_px, out_path, threads, tonemap_chain, preview=preview
        )
    return out_path


def render_segments(
    edl: dict, manifest: dict, session_dir: Path, threads: int, tonemap_chain: str = ""
) -> list[Path]:
    """Render every clip of the EDL at final resolution, per #10.1.

    Args:
        edl: EDL dict, as returned by `edl.build_edl`. Reads `clips`.
        manifest: Manifest dict. Reads `sources`.
        session_dir: Session root directory.
        threads: ffmpeg thread count.
        tonemap_chain: HDR (HLG/DV84) tonemap filter chain.

    Returns:
        Paths to the rendered final-resolution segments, one per clip, in
        clip order, under `session_dir / "segments"`.
    """
    sources_by_src = {s["src"]: s for s in manifest["sources"]}
    out_dir = session_dir / "segments"
    return [
        render_segment(
            clip,
            sources_by_src,
            session_dir,
            out_dir,
            threads,
            tonemap_chain,
            preview=False,
        )
        for clip in edl["clips"]
    ]


def render_preview_segments(
    edl: dict,
    manifest: dict,
    session_dir: Path,
    threads: int,
    tonemap_chain: str = "",
) -> list[Path]:
    """Render every clip of the EDL at preview resolution, per #10.2.

    Args:
        edl: EDL dict, as returned by `edl.build_edl`. Reads `clips`.
        manifest: Manifest dict. Reads `sources`.
        session_dir: Session root directory.
        threads: ffmpeg thread count.
        tonemap_chain: HDR (HLG/DV84) tonemap filter chain.

    Returns:
        Paths to the rendered preview-resolution segments, one per clip, in
        clip order, under `session_dir / "preview_segments"`.
    """
    sources_by_src = {s["src"]: s for s in manifest["sources"]}
    out_dir = session_dir / "preview_segments"
    return [
        render_segment(
            clip,
            sources_by_src,
            session_dir,
            out_dir,
            threads,
            tonemap_chain,
            preview=True,
        )
        for clip in edl["clips"]
    ]
