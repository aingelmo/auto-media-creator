"""Regression test for the preview_suffix bug (#run_render_checks)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from edl_agent.render.checks import CheckResult, run_render_checks


def _edl():
    return {
        "clips": [{"slot": 0, "n_frames": 10}],
        "target": {"duration_f": 10},
        "audio": {},
    }


def test_run_render_checks_uses_preview_suffix_for_preview_dir(tmp_path: Path):
    seen_preview_paths = []

    def fake_r2(final_seg, preview_seg, n_frames):
        seen_preview_paths.append(preview_seg)
        return CheckResult("R2", True)

    with (
        patch("edl_agent.render.checks.check_r1_frame_count", return_value=CheckResult("R1", True)),
        patch("edl_agent.render.checks.check_r2_phash", side_effect=fake_r2),
        patch("edl_agent.render.checks.check_r3_reel_duration", return_value=CheckResult("R3", True)),
        patch("edl_agent.render.checks.check_r4_color", return_value=CheckResult("R4", True)),
        patch("edl_agent.render.checks.check_r5_loudnorm_linear", return_value=CheckResult("R5", True)),
        patch("edl_agent.render.checks.check_r6_monotonic_dts", return_value=CheckResult("R6", True)),
    ):
        run_render_checks(_edl(), tmp_path, preview_suffix="_h0p1")

    assert seen_preview_paths == [tmp_path / "preview_segments_h0p1" / "seg_00.mp4"]
