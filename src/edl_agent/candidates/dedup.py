"""Temporal NMS + pHash dedup for peak/calm windows, per #4.3.

Both passes run on `window` dicts (see `peaks.find_peak_windows`,
`calm.find_calm_windows`) *before* `build.build_video_candidates` assigns
ids and extracts the final peak frames, so suppressed/duplicate windows
never cost an id or an ffmpeg call for the full 3-frame extraction.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import imagehash
from PIL import Image

from edl_agent.candidates._common import (
    PEAK_MAX_PER_CLIP,
    PEAK_NMS_IOU_MAX,
    PEAK_PHASH_MAX_DISTANCE,
    bbox_area,
    window_bbox,
)


def _window_iou(a: list[float], b: list[float]) -> float:
    lo, hi = max(a[0], b[0]), min(a[1], b[1])
    inter = max(0.0, hi - lo)
    union = min(a[1] - a[0], b[1] - b[0])
    return inter / union if union > 0 else 0.0


def suppress_peak_windows(windows: list[dict], features: dict) -> list[dict]:
    """Greedy temporal NMS over `peak` windows, per #4.3.

    Sibling peaks whose windows overlap heavily (IoU > `PEAK_NMS_IOU_MAX`)
    are collapsed to the highest-`kp_speed_abs` one; survivors are then
    capped to the `PEAK_MAX_PER_CLIP` highest-scoring per clip. Without
    this, `_peak_window`'s neighbor-midpoint cap still leaves near-duplicate
    windows when several peaks cluster close together (#4.3).

    Args:
        windows: `peak`-kind window dicts (see `peaks.find_peak_windows`),
            all from the same clip.
        features: Feature series for the clip; `kp_speed_abs` ranks windows
            since it's comparable across clips, unlike the per-clip
            p5-95-normalized `kp_speed` (falls back to a constant rank,
            i.e. window order, if the key is missing).

    Returns:
        Surviving windows, in their original relative order.
    """
    if not windows:
        return windows
    kp_speed_abs = features.get("kp_speed_abs")
    ranked = sorted(
        windows,
        key=lambda w: kp_speed_abs[w["index"]] if kp_speed_abs else 0.0,
        reverse=True,
    )
    kept: list[dict] = []
    for w in ranked:
        if any(_window_iou(w["window"], k["window"]) > PEAK_NMS_IOU_MAX for k in kept):
            continue
        kept.append(w)
        if len(kept) >= PEAK_MAX_PER_CLIP:
            break
    kept_ids = {id(w) for w in kept}
    return [w for w in windows if id(w) in kept_ids]


def _probe_frame(proxy_path: str, t: float, out_path: Path) -> None:
    """Extract one small low-cost JPEG at `t`, for pHash comparison only."""
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
        "scale=128:-2",
        "-q:v",
        "6",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def dedup_windows_by_phash(
    windows: list[dict], proxy_path: str, features: dict
) -> list[dict]:
    """Drop visually near-identical windows via perceptual hash, per #4.3.

    Complements `suppress_peak_windows`: two peaks far enough apart in time
    to survive the temporal-overlap NMS can still be the same visual moment
    (the same rep with a brief drop in speed between, or a static hold
    logged as two separate calm runs). Extracts one small probe frame per
    window at `t_peak` (cheaper than the final 3-frame extraction) and,
    among windows within `PEAK_PHASH_MAX_DISTANCE` Hamming bits of each
    other, keeps the one with the largest subject bbox (the closest framing
    of near-duplicate shots; #4.3 LLM rejection bucket: "sujeto pequeño"),
    using the same `imagehash.phash` convention as `verify.py`'s `_phash`.

    Args:
        windows: Window dicts (peak or calm), all from the same clip.
        proxy_path: Path to the proxy video to probe frames from.
        features: Feature series for the clip, used to look up each
            window's subject bbox (see `_common.window_bbox`).

    Returns:
        Surviving windows, in their original relative (temporal) order.
    """
    if len(windows) <= 1:
        return windows
    with tempfile.TemporaryDirectory() as tmp:
        hashes = []
        for i, w in enumerate(windows):
            probe_path = Path(tmp) / f"probe_{i}.jpg"
            _probe_frame(proxy_path, w["t_peak"], probe_path)
            hashes.append(imagehash.phash(Image.open(probe_path)))

    areas = [bbox_area(window_bbox(features, w)) for w in windows]
    order = sorted(range(len(windows)), key=lambda i: areas[i], reverse=True)
    kept: set[int] = set()
    for i in order:
        if any(hashes[i] - hashes[k] <= PEAK_PHASH_MAX_DISTANCE for k in kept):
            continue
        kept.add(i)
    return [w for i, w in enumerate(windows) if i in kept]
