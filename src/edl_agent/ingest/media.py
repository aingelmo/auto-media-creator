"""Image normalization (#3.3) and music trimming (#3.4)."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pillow_heif
from PIL import Image, ImageOps

if TYPE_CHECKING:
    from pathlib import Path

pillow_heif.register_heif_opener()


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
