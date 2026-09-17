"""#6.7 colour matching: pure math + ffmpeg measurement on lavfi clips."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING, Any

from edl_agent.planner import apply_color_match, color_fix_for, measure_clip_color

if TYPE_CHECKING:
    from pathlib import Path

_GREY = {"y": 128.0, "u": 128.0, "v": 128.0, "sat": 10.0}


def _make_color(path: Path, color: str, duration: float = 1) -> None:
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color={color}:size=64x64:rate=30",
        "-t",
        str(duration),
        "-pix_fmt",
        "yuv420p",
        str(path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def test_color_fix_identity_when_equal() -> None:
    fix = color_fix_for(_GREY, _GREY, 0.7)
    assert fix["brightness"] == 0
    assert set(fix) == {"brightness", "measured"}  # luma-only, no chroma keys


def test_color_fix_dark_clip_brightens_and_clamps() -> None:
    dark = {**_GREY, "y": 50.0, "sat": 5.0}
    fix = color_fix_for(dark, _GREY, 1.0)
    assert 0 < fix["brightness"] <= 0.15
    extreme = color_fix_for({"y": 0.0, "u": 0.0, "v": 255.0, "sat": 0.0}, _GREY, 1.0)
    assert extreme["brightness"] == 0.15
    bright = color_fix_for({**_GREY, "y": 250.0}, _GREY, 1.0)
    assert bright["brightness"] == 0  # lift-only, never darkens


def test_measure_and_apply_on_two_clips(tmp_path: Path) -> None:
    _make_color(tmp_path / "dark.mp4", "0x333333")
    _make_color(tmp_path / "bright.mp4", "0xcccccc")
    dark = measure_clip_color(str(tmp_path / "dark.mp4"), 0.0, 0.5)
    bright = measure_clip_color(str(tmp_path / "bright.mp4"), 0.0, 0.5)
    assert 40 < dark["y"] < 70
    assert 170 < bright["y"] < 200

    manifest = {
        "sources": [
            {"src": "dark.mp4", "proxy": "dark.mp4"},
            {"src": "bright.mp4", "proxy": "bright.mp4"},
        ]
    }
    clips: list[dict[str, Any]] = [
        {"src": s, "type": "video", "in_s": 0.0, "out_s": 0.5, "n_frames": 15}
        for s in ("dark.mp4", "bright.mp4")
    ]
    edl: dict[str, Any] = {"clips": clips}
    apply_color_match(
        edl, manifest, tmp_path, {"color_match": True, "color_match_strength": 0.7}
    )
    assert edl["clips"][0]["color_fix"]["brightness"] > 0
    assert edl["clips"][1]["color_fix"]["brightness"] == 0

    edl2: dict[str, Any] = {"clips": [dict(c) for c in edl["clips"]]}
    for c in edl2["clips"]:
        del c["color_fix"]
    apply_color_match(edl2, manifest, tmp_path, {"color_match": False})
    assert "color_fix" not in edl2["clips"][0]
