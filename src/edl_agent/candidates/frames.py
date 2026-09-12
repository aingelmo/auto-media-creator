"""Peak-frame JPEG extraction and human-inspection contact sheets, per #4.3."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from edl_agent.candidates._common import PEAK_FRAME_OFFSETS_S, PEAK_FRAME_SIDE_PX

if TYPE_CHECKING:
    from pathlib import Path


def extract_peak_frames(
    proxy_path: str,
    t_peak: float,
    window: tuple[float, float],
    out_dir: Path,
    cand_id: str,
) -> tuple[list[str], list[str]]:
    """Extract the `peak_frames` JPEGs for a candidate, per #4.3.

    Extracts 3 frames at `t_peak + PEAK_FRAME_OFFSETS_S` (before/at/after the
    peak), each timestamp clamped to `window`, via ffmpeg.

    Args:
        proxy_path: Path to the proxy video to extract frames from.
        t_peak: Timestamp of the candidate's peak, in seconds.
        window: `(start_s, end_s)` bounds to clamp extraction timestamps to.
        out_dir: Directory to write the JPEGs to (created if missing).
        cand_id: Candidate id (e.g. `"c01"`), used as the output filename
            prefix.

    Returns:
        `(paths, hashes)`: parallel lists of output file paths (as `str`)
        and their SHA-256 hex digests, in the same order as
        `PEAK_FRAME_OFFSETS_S`.

    Raises:
        subprocess.CalledProcessError: If any ffmpeg invocation fails.
    """
    from edl_agent.ingest import sha256_file

    out_dir.mkdir(parents=True, exist_ok=True)
    scale = (
        f"scale='if(gt(iw,ih),{PEAK_FRAME_SIDE_PX},-2)':"
        f"'if(gt(iw,ih),-2,{PEAK_FRAME_SIDE_PX})'"
    )
    paths, hashes = [], []
    for i, off in enumerate(PEAK_FRAME_OFFSETS_S):
        t = min(max(t_peak + off, window[0]), window[1])
        out_path = out_dir / f"{cand_id}_{i}.jpg"
        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            str(max(t, 0.0)),
            "-i",
            str(proxy_path),
            "-frames:v",
            "1",
            "-vf",
            scale,
            "-q:v",
            "4",
            str(out_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        paths.append(str(out_path))
        hashes.append(sha256_file(out_path))
    return paths, hashes


def build_contact_sheet(peak_frame_paths: list[str], out_path: Path) -> Path:
    """Build a horizontal contact sheet from a candidate's peak frames.

    For human inspection only (#4.3); not consumed by the LLM selector or
    the planner.

    Args:
        peak_frame_paths: Paths to the JPEG frames to lay out side by side,
            in order.
        out_path: Path to write the JPEG contact sheet to (parent directory
            created if missing).

    Returns:
        `out_path`, unchanged, for convenient chaining.
    """
    from PIL import Image

    images = [Image.open(p) for p in peak_frame_paths]
    h = max(im.height for im in images)
    resized = [im.resize((round(im.width * h / im.height), h)) for im in images]
    sheet = Image.new("RGB", (sum(im.width for im in resized), h))
    x = 0
    for im in resized:
        sheet.paste(im, (x, 0))
        x += im.width
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, "JPEG", quality=85)
    return out_path
