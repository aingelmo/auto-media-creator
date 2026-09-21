"""Regression test for the preview_suffix bug (#run_render_checks)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

from edl_agent.render.checks import CheckResult, run_render_checks

if TYPE_CHECKING:
    from pathlib import Path


def _edl():
    return {
        "clips": [{"slot": 0, "n_frames": 10}],
        "target": {"duration_f": 10},
        "audio": {},
    }


def _ok(check: str, tag: str):
    return patch(
        f"edl_agent.render.checks.{check}", return_value=CheckResult(tag, True)
    )


def test_run_render_checks_uses_preview_suffix_for_preview_dir(tmp_path: Path):
    seen_preview_paths = []

    def fake_r2(final_seg, preview_seg, n_frames):
        seen_preview_paths.append(preview_seg)
        return CheckResult("R2", True)

    with (
        _ok("check_r1_frame_count", "R1"),
        patch("edl_agent.render.checks.check_r2_phash", side_effect=fake_r2),
        _ok("check_r3_reel_duration", "R3"),
        _ok("check_r4_color", "R4"),
        _ok("check_r5_loudnorm_linear", "R5"),
        _ok("check_r6_monotonic_dts", "R6"),
    ):
        run_render_checks(_edl(), tmp_path, preview_suffix="_h0p1")

    assert seen_preview_paths == [tmp_path / "preview_segments_h0p1" / "seg_00.mp4"]
