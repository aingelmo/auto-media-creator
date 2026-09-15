"""Video source probing (ffprobe, HDR classification), per #3.1."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING

from edl_agent.ingest._common import IngestError, sha256_file

if TYPE_CHECKING:
    from pathlib import Path


def ffprobe(path: Path) -> dict:
    """Run `ffprobe -show_streams -show_format` and return the parsed JSON.

    Args:
        path: Path to the media file to probe.

    Returns:
        Parsed ffprobe JSON output, with top-level keys `format` and
        `streams` (list of stream dicts).

    Raises:
        subprocess.CalledProcessError: If ffprobe exits with a non-zero
            status.
    """
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(out.stdout)


def _video_stream(probe: dict) -> dict:
    for s in probe["streams"]:
        if s["codec_type"] == "video":
            return s
    msg = f"no video stream in probe: {probe}"
    raise IngestError(msg)


def _rotation(stream: dict) -> int:
    for sd in stream.get("side_data_list", []):
        if "rotation" in sd:
            return int(sd["rotation"])
    # some containers expose rotation as a tag instead of side_data
    tag = stream.get("tags", {}).get("rotate")
    return int(tag) if tag else 0


def classify_hdr(stream: dict) -> str:
    """Classify a video stream's HDR type, per #3.1.

    Args:
        stream: An ffprobe video stream dict (as returned by
            `_video_stream`). Reads `color_transfer`, `pix_fmt`, and
            `side_data_list`.

    Returns:
        One of `"none"`, `"hlg"`, `"pq"`, `"dv84"`.

    Raises:
        IngestError: If the stream is 10-bit with no `color_transfer` tag
            (#3.1's ingestion-failure rule: refuses to silently assume SDR
            rather than mis-tonemap the footage).
    """
    transfer = stream.get("color_transfer")
    is_10bit = "10" in stream.get("pix_fmt", "") or "p10" in stream.get("pix_fmt", "")

    has_dolby_vision = any(
        sd.get("side_data_type", "").lower().startswith("dovi")
        for sd in stream.get("side_data_list", [])
    )
    if has_dolby_vision and transfer == "arib-std-b67":
        return "dv84"
    if transfer == "arib-std-b67":
        return "hlg"
    if transfer == "smpte2084":
        return "pq"
    if is_10bit and transfer in (None, "unknown", ""):
        msg = (
            "10-bit source without color_transfer: refusing to assume SDR "
            f"(stream={stream.get('index')})"
        )
        raise IngestError(
            msg,
        )
    return "none"


def _fps(stream: dict) -> float:
    """Parse a video stream's nominal fps from `avg_frame_rate`."""
    num, den = (
        (int(x) for x in stream["avg_frame_rate"].split("/"))
        if "/" in stream.get("avg_frame_rate", "0/1")
        else (0, 1)
    )
    return round(num / den, 3) if den else 0.0


def _vfr(stream: dict) -> bool:
    r = stream.get("r_frame_rate")
    a = stream.get("avg_frame_rate")
    return bool(r and a and r != a)


@dataclass
class VideoSourceInfo:
    """Normalized metadata for one video source, for the manifest (#3.1)."""

    src: str
    sha256: str
    type: str
    raw_w: int
    raw_h: int
    rotation: int
    w: int
    h: int
    duration_s: float
    start_time_s: float
    nb_frames_est: int
    vfr: bool
    src_fps_nominal: float
    hdr: str
    color: dict
    has_audio: bool


def post_rotation_dims(raw_w: int, raw_h: int, rotation: int) -> tuple[int, int]:
    """Compute dimensions after applying the container rotation.

    Args:
        raw_w: Raw (unrotated) width, in pixels.
        raw_h: Raw (unrotated) height, in pixels.
        rotation: Rotation, in degrees (e.g. 0, 90, 180, 270, or negative
            equivalents).

    Returns:
        `(w, h)`: `(raw_h, raw_w)` if `rotation` is +-90/270 (swapped),
        otherwise `(raw_w, raw_h)` unchanged.
    """
    return (raw_h, raw_w) if abs(rotation) in (90, 270) else (raw_w, raw_h)


def probe_video_source(path: Path) -> VideoSourceInfo:
    """Build a `VideoSourceInfo` from `ffprobe`, per #3.1.

    Args:
        path: Path to the video source file.

    Returns:
        Populated `VideoSourceInfo` for this source.

    Raises:
        IngestError: If the file has no video stream, or its HDR
            classification fails (see `classify_hdr`).
    """
    probe = ffprobe(path)
    stream = _video_stream(probe)

    raw_w, raw_h = int(stream["width"]), int(stream["height"])
    rotation = _rotation(stream)
    w, h = post_rotation_dims(raw_w, raw_h, rotation)

    hdr = classify_hdr(stream)

    duration_s = float(stream.get("duration") or probe["format"]["duration"])
    start_time_s = float(
        stream.get("start_time", probe["format"].get("start_time", 0.0))
    )

    fps_nominal = _fps(stream)
    nb_frames_est = (
        round(duration_s * fps_nominal)
        if fps_nominal
        else int(stream.get("nb_frames", 0))
    )

    color = {
        "primaries": stream.get("color_primaries", "unknown"),
        "trc": stream.get("color_transfer", "unknown"),
        "space": stream.get("color_space", "unknown"),
        "range": stream.get("color_range", "unknown"),
    }

    return VideoSourceInfo(
        src=str(path),
        sha256=sha256_file(path),
        type="video",
        raw_w=raw_w,
        raw_h=raw_h,
        rotation=rotation,
        w=w,
        h=h,
        duration_s=duration_s,
        start_time_s=start_time_s,
        nb_frames_est=nb_frames_est,
        vfr=_vfr(stream),
        src_fps_nominal=fps_nominal,
        hdr=hdr,
        color=color,
        has_audio=any(s["codec_type"] == "audio" for s in probe["streams"]),
    )
