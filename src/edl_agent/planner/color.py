"""#6.7 Per-clip colour matching: measure each clip, pull outliers toward the median."""

from __future__ import annotations

import json
import statistics
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

_KEYS = {"y": "YAVG", "u": "UAVG", "v": "VAVG", "sat": "SATAVG"}


def measure_clip_color(path: str, in_s: float, dur_s: float) -> dict:
    """Mean `signalstats` Y/U/V/SAT (0-255) over `[in_s, in_s + dur_s)` of `path`.

    Args:
        path: Video (proxy) or image file.
        in_s: Start offset in seconds (ignored for single-frame images).
        dur_s: Duration to measure, in seconds.

    Returns:
        `{"y", "u", "v", "sat"}` floats averaged over the measured frames.

    Raises:
        subprocess.CalledProcessError: If ffprobe fails.
    """
    entries = ",".join(f"lavfi.signalstats.{k}" for k in _KEYS.values())
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"movie={path}:seek_point={in_s},trim=duration={dur_s},signalstats",
        "-show_entries",
        f"frame_tags={entries}",
        "-of",
        "json",
    ]
    out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    frames = [f["tags"] for f in json.loads(out)["frames"]]
    return {
        k: statistics.fmean(float(t[f"lavfi.signalstats.{tag}"]) for t in frames)
        for k, tag in _KEYS.items()
    }


def _clamp(x: float, lo: float, hi: float) -> float:
    return round(max(lo, min(hi, x)), 4)


def color_fix_for(measured: dict, target: dict, strength: float) -> dict:
    """Compute `eq` brightness moving `measured` toward `target`, luma-only.

    Gains verified empirically on ffmpeg 5.1: `eq=brightness=b` shifts Y by
    ~b*255.

    Chroma (U/V) matching was tried and removed: frame-mean U/V tracks what's
    in shot (skin, wood, sky), not white balance, so `colorcorrect` dragged
    neutrals off-neutral and read as an orange cast; `SATAVG` is too noisy at
    typical levels (single-digit values) to drive a saturation gain safely.
    Don't re-add either without a real white-balance measurement.

    Args:
        measured: `{"y", "u", "v", "sat"}` of the clip.
        target: Same keys, reel-wide target (median).
        strength: 0..1 fraction of the gap to close.

    Returns:
        `{"brightness", "measured"}`.
    """
    # ponytail: lift-only. Clips at Y~110+ (~45 IRE) are already well exposed
    # per colourist references; darkening them toward a median dragged down by
    # dark clips looked wrong. Add a "darken above Y>=X" rule if blown-out
    # sources show up.
    return {
        "brightness": _clamp(strength * (target["y"] - measured["y"]) / 255, 0, 0.15),
        "measured": measured,
    }


def apply_color_match(
    edl: dict, manifest: dict, session_dir: Path, config: dict
) -> None:
    """Set `clip["color_fix"]` on every EDL clip, in place (#6.7).

    Measures each clip on its proxy (video) or normalized image, takes the
    per-key median as target, and stores the correction. No-op when
    `config["color_match"]` is false or there are no clips.

    Args:
        edl: EDL dict; `clips` are mutated.
        manifest: Manifest dict, for `sources` (`proxy`/`normalized` paths).
        session_dir: Session root, to resolve those paths.
        config: Merged planner config (`color_match`, `color_match_strength`).
    """
    clips = [c for c in edl["clips"] if c.get("effect") != "end_card"]
    if not config.get("color_match") or not clips:
        return
    sources_by_src = {s["src"]: s for s in manifest["sources"]}
    measured = []
    for clip in clips:
        source = sources_by_src[clip["src"]]
        if clip["type"] == "image":
            measured.append(
                measure_clip_color(str(session_dir / source["normalized"]), 0, 1)
            )
        else:
            dur = clip["out_s"] - clip["in_s"]
            measured.append(
                measure_clip_color(
                    str(session_dir / source["proxy"]), clip["in_s"], dur
                )
            )
    target = {k: statistics.median(m[k] for m in measured) for k in _KEYS}
    strength = config["color_match_strength"]
    for clip, m in zip(clips, measured, strict=True):
        clip["color_fix"] = color_fix_for(m, target, strength)
