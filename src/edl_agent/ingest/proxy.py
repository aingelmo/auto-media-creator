"""Working proxy generation for video sources, per #3.2."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from edl_agent.ffmpeg import ffmpeg_bin, has_filter
from edl_agent.ingest._common import IngestError

if TYPE_CHECKING:
    from pathlib import Path

    from .probe import VideoSourceInfo

PROXY_SHORT_SIDE = 720

# Tonemap chain for proxy/preview/render; fixed here for the whole session (#3.2).
# npl=203 = HLG reference white (BT.2408); npl=1000 crushed DV84 clips to Y~62
# vs ~110 for SDR clips of the same scene (measured 2026-09-15).
TONEMAP_CHAIN_HLG = (
    "zscale=tin=arib-std-b67:t=linear:npl=203,format=gbrpf32le,"
    "zscale=p=bt709,tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv"
)

# Fallback HDR chain for ffmpeg builds without the `zscale` filter (e.g.
# linuxbrew ffmpeg 9, which ships `tonemap`+`colorspace` but no zscale).
# Uses mobius instead of hable: fed with HLG-encoded (non-linear) input,
# hable crushes midtones (measured Y~57 vs ~110 for SDR footage of the
# same scene), while mobius lands at Y~117 (measured 2026-09-29, checked
# visually on indoor footage). `iall=bt2020` is required: without an
# explicit input side, `colorspace` errors out instead of reading the
# frame metadata.
TONEMAP_CHAIN_HLG_BASIC = "tonemap=mobius:desat=0,colorspace=all=bt709:iall=bt2020"


def _has_zscale() -> bool:
    """Check whether this machine's ffmpeg provides the `zscale` filter."""
    return has_filter("zscale")


def tonemap_chain_hlg() -> str:
    """Return the HLG/DV84 tonemap chain supported by this ffmpeg (#3.2).

    Returns:
        `TONEMAP_CHAIN_HLG` when the `zscale` filter is available, else
        `TONEMAP_CHAIN_HLG_BASIC`. Proxy, verify, and render must all use
        this selector (never the constants directly) so the chain stays
        identical across stages within a session.
    """
    return TONEMAP_CHAIN_HLG if _has_zscale() else TONEMAP_CHAIN_HLG_BASIC


def build_proxy(info: VideoSourceInfo, out_path: Path, threads: int = 4) -> Path:
    """Generate the working proxy for a video source, per #3.2.

    HDR sources (hlg/dv84) are tonemapped via `tonemap_chain_hlg()`; the
    rest (none; pq not yet supported) go through untouched aside from
    scaling.

    Args:
        info: Probed source info, as returned by `probe.probe_video_source`.
            Uses `.hdr` and `.src`.
        out_path: Output proxy path (parent directory created if missing).
        threads: ffmpeg thread count. Defaults to 4.

    Returns:
        `out_path`, unchanged, for convenient chaining.

    Raises:
        IngestError: If `info.hdr` is a value not yet supported by proxy
            generation (currently `"pq"`; see [validate] in #3.2), or if
            the ffmpeg invocation fails (stderr tail included).
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    scale = (
        f"scale='if(gt(iw,ih),-2,{PROXY_SHORT_SIDE})':"
        f"'if(gt(iw,ih),{PROXY_SHORT_SIDE},-2)'"
    )

    if info.hdr in ("hlg", "dv84"):
        vf = f"fps=30,setpts=PTS-STARTPTS,{tonemap_chain_hlg()},format=yuv420p,{scale}"
    elif info.hdr == "none":
        vf = f"fps=30,setpts=PTS-STARTPTS,{scale},format=yuv420p"
    else:
        msg = (
            f"proxy generation for hdr={info.hdr!r} not implemented "
            "(see [validate] in #3.2)"
        )
        raise IngestError(msg)

    cmd = [
        ffmpeg_bin(),
        "-y",
        "-i",
        info.src,
        "-vf",
        vf,
        "-fps_mode",
        "cfr",
        "-avoid_negative_ts",
        "make_zero",
        "-color_primaries",
        "bt709",
        "-color_trc",
        "bt709",
        "-colorspace",
        "bt709",
        "-color_range",
        "tv",
        # ffmpeg 9's `-color_*` no longer writes H.264 VUI
        # primaries/transfer: force them (1/1/1 = bt709) so the
        # proxy probes as SDR bt709 downstream.
        "-bsf:v",
        (
            "h264_metadata=colour_primaries=1:transfer_characteristics=1"
            ":matrix_coefficients=1"
        ),
        "-c:v",
        "libx264",
        # No B-frames: with them, libx264's negative initial DTS (from frame
        # reordering) forces -avoid_negative_ts to shift the whole timeline
        # forward by the reorder delay, skewing frame 0's PTS off zero and
        # desyncing proxy timestamps from the original (#4.4 false positives).
        "-bf",
        "0",
        "-crf",
        "24",
        "-preset",
        "veryfast",
        "-g",
        "30",
        "-threads",
        str(threads),
        "-an",
        str(out_path),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        # CalledProcessError alone hides ffmpeg's stderr from job logs;
        # include its tail so filter errors (e.g. missing `zscale`) are
        # diagnosable without re-running the command by hand.
        stderr_tail = (exc.stderr or "").strip().splitlines()[-5:]
        msg = f"ffmpeg proxy failed for {info.src} ({' '.join(stderr_tail)})"
        raise IngestError(msg) from exc
    return out_path
