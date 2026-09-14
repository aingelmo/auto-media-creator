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
    assert (fix["brightness"], fix["saturation"], fix["rl"], fix["bl"]) == (
        0,
        1.0,
        0,
        0,
    )


def test_color_fix_dark_clip_brightens_and_clamps() -> None:
    dark = {**_GREY, "y": 50.0, "sat": 5.0}
    fix = color_fix_for(dark, _GREY, 1.0)
    assert 0 < fix["brightness"] <= 0.15
    assert fix["saturation"] == 1.15  # ratio 2.0 clamped
    extreme = color_fix_for({"y": 0.0, "u": 0.0, "v": 255.0, "sat": 0.0}, _GREY, 1.0)
    assert extreme["brightness"] == 0.15
    assert extreme["bl"] == 0.10
    assert extreme["rl"] == -0.10
    assert extreme["saturation"] == 1.0  # sat=0 -> no ratio, identity
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
    edl: dict[str, Any] = {
        "clips": [
            {"src": s, "type": "video", "in_s": 0.0, "n_frames": 15, "speed": 1.0}
            for s in ("dark.mp4", "bright.mp4")
        ]
    }
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
