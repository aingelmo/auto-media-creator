"""Layer 1 - Ingestion.

manifest.json, proxies, image normalization, music trimming.
See docs/architecture/arquitectura_edl_agent_v4.md #3.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pillow_heif
from PIL import Image, ImageOps

if TYPE_CHECKING:
    from pathlib import Path

pillow_heif.register_heif_opener()

TARGET = {"w": 1080, "h": 1920, "fps": 30}
PROXY_SHORT_SIDE = 720

# Tonemap chain for proxy/preview/render; fixed here for the whole session (#3.2).
TONEMAP_CHAIN_HLG = (
    "zscale=tin=arib-std-b67:t=linear:npl=1000,format=gbrpf32le,"
    "zscale=p=bt709,tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv"
)


class IngestError(RuntimeError):
    """A source was rejected during ingestion (e.g. 10-bit without color_transfer)."""


def sha256_file(path: Path) -> str:
    """Compute the SHA-256 hash of a file's contents, read in 1 MiB chunks.

    Args:
        path: Path to the file to hash.

    Returns:
        SHA-256 hex digest of the file's contents.
    """
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


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

    num, den = (
        (int(x) for x in stream["avg_frame_rate"].split("/"))
        if "/" in stream.get("avg_frame_rate", "0/1")
        else (0, 1)
    )
    fps_nominal = round(num / den, 3) if den else 0.0
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
    )


def build_proxy(info: VideoSourceInfo, out_path: Path, threads: int = 4) -> Path:
    """Generate the working proxy for a video source, per #3.2.

    HDR sources (hlg/dv84) are tonemapped via zscale+tonemap; the rest
    (none; pq not yet supported) go through untouched aside from scaling.

    Args:
        info: Probed source info, as returned by `probe_video_source`. Uses
            `.hdr` and `.src`.
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


def normalize_image(path: Path, out_path: Path) -> tuple[int, int]:
    """Normalize an image source, per #3.3 (EXIF transpose, convert to RGB JPEG).

    Args:
        path: Path to the source image (may be HEIC/HEIF, JPEG, PNG, etc.).
        out_path: Output JPEG path (parent directory created if missing).

    Returns:
        `(w, h)` of the normalized image, in pixels.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.open(path)
    im = ImageOps.exif_transpose(im)
    im = im.convert("RGB")
    im.save(out_path, "JPEG", quality=92, icc_profile=None)
    return im.size


def cut_music(
    src: Path, out_path: Path, offset_s: float, max_duration_s: float
) -> Path:
    """Trim the music track once, to WAV, per #3.4.

    Everything downstream (beat detection, loudnorm, render) uses this
    single trimmed file.

    Args:
        src: Path to the source music file.
        out_path: Output WAV path (parent directory created if missing).
        offset_s: Start offset into `src`, in seconds.
        max_duration_s: Maximum duration to keep, in seconds.

    Returns:
        `out_path`, unchanged, for convenient chaining.

    Raises:
        subprocess.CalledProcessError: If the ffmpeg invocation fails.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        str(offset_s),
        "-t",
        str(max_duration_s),
        "-i",
        str(src),
        "-ar",
        "48000",
        "-ac",
        "2",
        "-c:a",
        "pcm_s16le",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return out_path


def build_manifest(
    session_id: str, sources: list[dict], music: dict | None = None
) -> dict:
    """Assemble the manifest.json dict from already-probed sources.

    Args:
        session_id: Identifier of the session, copied into the manifest.
        sources: Per-source entries as built by `session.run_ingest` (each
            a dict with at least `src`, `sha256`, `type`, plus
            video-specific or image-specific fields).
        music: Music entry, or `None` if no music track was provided. Keys:
            `src`, `src_sha256`, `offset_s`, `max_duration_s`, `cut`,
            `cut_sha256`.

    Returns:
        Manifest dict with keys `session_id`, `target` (copy of `TARGET`),
        `sources`, and `music` (only present if `music` was given).
    """
    manifest = {
        "session_id": session_id,
        "target": dict(TARGET),
        "sources": sources,
    }
    if music is not None:
        manifest["music"] = music
    return manifest


def write_manifest(manifest: dict, path: Path) -> None:
    """Write manifest.json to `path`, creating the parent directory if missing.

    Args:
        manifest: Manifest dict, as returned by `build_manifest`.
        path: Output path for the JSON file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
