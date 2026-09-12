"""Working proxy generation for video sources, per #3.2."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from edl_agent.ingest._common import IngestError

if TYPE_CHECKING:
    from pathlib import Path

    from .probe import VideoSourceInfo

PROXY_SHORT_SIDE = 720

# Tonemap chain for proxy/preview/render; fixed here for the whole session (#3.2).
TONEMAP_CHAIN_HLG = (
    "zscale=tin=arib-std-b67:t=linear:npl=1000,format=gbrpf32le,"
    "zscale=p=bt709,tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv"
)


def build_proxy(info: VideoSourceInfo, out_path: Path, threads: int = 4) -> Path:
    """Generate the working proxy for a video source, per #3.2.

    HDR sources (hlg/dv84) are tonemapped via zscale+tonemap; the rest
    (none; pq not yet supported) go through untouched aside from scaling.

    Args:
        info: Probed source info, as returned by `probe.probe_video_source`.
            Uses `.hdr` and `.src`.
        out_path: Output proxy path (parent directory created if missing).
        threads: ffmpeg thread count. Defaults to 4.

    Returns:
        `out_path`, unchanged, for convenient chaining.

    Raises:
        IngestError: If `info.hdr` is a value not yet supported by proxy
            generation (currently `"pq"`; see [validate] in #3.2).
        subprocess.CalledProcessError: If the ffmpeg invocation fails.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    scale = (
        f"scale='if(gt(iw,ih),-2,{PROXY_SHORT_SIDE})':"
        f"'if(gt(iw,ih),{PROXY_SHORT_SIDE},-2)'"
    )

    if info.hdr in ("hlg", "dv84"):
        vf = f"fps=30,setpts=PTS-STARTPTS,{TONEMAP_CHAIN_HLG},format=yuv420p,{scale}"
    elif info.hdr == "none":
        vf = f"fps=30,setpts=PTS-STARTPTS,{scale},format=yuv420p"
    else:
        msg = (
            f"proxy generation for hdr={info.hdr!r} not implemented "
            "(see [validate] in #3.2)"
        )
        raise IngestError(msg)

    cmd = [
        "ffmpeg",
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
        "-c:v",
        "libx264",
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
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return out_path
