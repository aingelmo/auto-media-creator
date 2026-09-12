"""Layer 1 - Temporal proxy <-> original verification (#4.4).

In Layer 1 (before kp_speed exists, which is computed in Layer 2) the test
instants are the percentile {10%, 50%, 90%} fallback over the duration. Once
Layer 2 provides kp_speed peaks, they are passed in as `extra_instants_s` and
take priority (filled out with percentiles up to 5 if needed).
"""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import imagehash
from PIL import Image

FRAME_OFFSETS = (-2, -1, 0, 1, 2)  # proxy frames to compare, at 30 fps
D0_MAX = 6  # threshold [validate margin] per #4.4
# Margin between d0 and the neighbors' minimum: in static/slow-motion scenes,
# pHash noise (and the HDR tonemap itself) can make a neighbor score a few
# bits below d0 without any actual content difference (see real sessions
# #4.4). A genuine misalignment drives d0 far above D0_MAX in at least one
# instant, so this margin doesn't mask real errors.
BEST_MARGIN = 4


@dataclass
class InstantResult:
    """Result of #4.4 at one instant: original vs proxy pHash at several offsets."""

    t_s: float
    distances: dict[int, int]  # offset -> hamming distance
    ok: bool


def pick_instants(
    duration_s: float, extra_instants_s: list[float] | None = None
) -> list[float]:
    """Choose instants to verify, per #4.4.

    Args:
        duration_s: Proxy duration, in seconds.
        extra_instants_s: Priority instants (e.g. kp_speed peaks from
            Layer 2), in seconds; filled out with the 10th/50th/90th
            percentile of `duration_s` up to 5 total instants.

    Returns:
        Up to 5 instants to verify, in seconds.
    """
    extra = sorted(set(extra_instants_s or []))
    percentiles = [duration_s * p for p in (0.10, 0.50, 0.90)]
    instants = list(extra)
    for p in percentiles:
        if len(instants) >= 5:
            break
        if all(abs(p - i) >= 2.0 for i in instants):
            instants.append(p)
    return instants[:5]


# ffmpeg's `-ss` seeks to the first frame whose pts >= the requested time
# (ceiling), not the nearest one; on an arbitrary (non-frame-aligned) instant
# this can grab the *next* frame instead of the intended one. Snapping to the
# exact pts of the target frame on its own fps grid, minus a tiny epsilon,
# makes the seek land on that exact frame regardless (see #4.4 investigation).
_SEEK_EPSILON_S = 1e-3


def _frame_seek_time(t: float, fps: float) -> float:
    """Snap `t` to the pts of its nearest frame on an `fps` grid."""
    return max(round(t * fps) / fps - _SEEK_EPSILON_S, 0.0)


def _extract_frame(cmd_extra: list[str], src: str, t: float, out_path: Path) -> None:
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        str(max(t, 0.0)),
        "-i",
        src,
        "-frames:v",
        "1",
        *cmd_extra,
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def _phash(path: Path) -> imagehash.ImageHash:
    with Image.open(path) as im:
        return imagehash.phash(im)


def _instant_ok(distances: dict[int, int]) -> bool:
    d0 = distances[0]
    best = min(distances.values())
    # #4.4 + risk #13: we don't require 0 to be the exact minimum (pHash
    # noise in static scenes can lose the tie without any real
    # misalignment); it's enough to be close to the best neighbor and below
    # the absolute threshold.
    return d0 <= D0_MAX and (d0 - best) <= BEST_MARGIN


def verify_source(
    original: str,
    proxy: str,
    tonemap_chain: str = "",
    extra_instants_s: list[float] | None = None,
    proxy_fps: int = 30,
) -> tuple[bool, list[InstantResult]]:
    """Verify that the proxy preserves the original's content, per #4.4.

    At each of `pick_instants`' chosen instants, extracts a frame from the
    original and, at several frame offsets, from the proxy, then compares
    pHash distances.

    Args:
        original: Path to the original video file.
        proxy: Path to the proxy video file.
        tonemap_chain: ffmpeg `-vf` filter chain to apply to the original
            frame before hashing (e.g. an HDR tonemap); `""` for none.
        extra_instants_s: Priority instants to verify, in seconds; see
            `pick_instants`.
        proxy_fps: Proxy frame rate, in fps, used to convert `FRAME_OFFSETS`
            (in frames) to seconds when extracting proxy frames.

    Returns:
        `(verified, results)`: `verified` is `True` if every instant passed
        `_instant_ok`; `results` is the list of per-instant
        `InstantResult`s.
    """
    from .ingest import (  # local import: avoids a cycle in unit tests
        _fps,
        _video_stream,
        ffprobe,
    )

    proxy_stream = _video_stream(ffprobe(Path(proxy)))
    duration_s = float(proxy_stream["duration"])
    orig_fps = _fps(_video_stream(ffprobe(Path(original))))
    instants = pick_instants(duration_s, extra_instants_s)

    orig_vf = f"{tonemap_chain},scale=256:-2" if tonemap_chain else "scale=256:-2"

    results: list[InstantResult] = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        for t in instants:
            orig_png = tmp_path / f"orig_{t:.3f}.png"
            _extract_frame(
                ["-vf", orig_vf], original, _frame_seek_time(t, orig_fps), orig_png
            )
            orig_hash = _phash(orig_png)

            proxy_frame = round(t * proxy_fps)
            distances: dict[int, int] = {}
            for k in FRAME_OFFSETS:
                proxy_png = tmp_path / f"proxy_{t:.3f}_{k}.png"
                proxy_t = _frame_seek_time(
                    (proxy_frame + k) / proxy_fps, proxy_fps
                )
                _extract_frame(["-vf", "scale=256:-2"], proxy, proxy_t, proxy_png)
                distances[k] = orig_hash - _phash(proxy_png)

            results.append(
                InstantResult(t_s=t, distances=distances, ok=_instant_ok(distances))
            )

    return all(r.ok for r in results), results
