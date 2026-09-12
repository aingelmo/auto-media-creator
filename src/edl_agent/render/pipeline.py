"""Orchestration (#8.5, #14 step 2): render + preview + concat + checks."""

from __future__ import annotations

from typing import TYPE_CHECKING

from edl_agent.render._common import RenderError
from edl_agent.render.checks import CheckResult, run_render_checks
from edl_agent.render.concat import concat_and_audio
from edl_agent.render.segments import render_preview_segments, render_segments

if TYPE_CHECKING:
    from pathlib import Path


def run_render(
    edl: dict,
    manifest: dict,
    session_dir: Path,
    threads: int = 4,
    tonemap_chain: str = "",
    allow_dynamic_loudnorm: bool = False,
) -> list[CheckResult]:
    """Run the full Layer 7 pipeline: render, concat audio, and run checks.

    Args:
        edl: EDL dict, as returned by `edl.build_edl`.
        manifest: Manifest dict.
        session_dir: Session root directory.
        threads: ffmpeg thread count.
        tonemap_chain: HDR (HLG/DV84) tonemap filter chain.
        allow_dynamic_loudnorm: Passed through to `run_render_checks`.

    Returns:
        The list of `CheckResult`s from `run_render_checks`, only if all of
        them passed.

    Raises:
        RenderError: If any of the R1-R6 checks fails; the message lists
            every failing check's name and detail.
        subprocess.CalledProcessError: If any underlying ffmpeg invocation
            fails.
    """
    render_segments(edl, manifest, session_dir, threads, tonemap_chain)
    render_preview_segments(edl, manifest, session_dir, threads, tonemap_chain)
    concat_and_audio(edl, session_dir, threads)
    results = run_render_checks(
        edl, session_dir, allow_dynamic_loudnorm=allow_dynamic_loudnorm
    )
    failed = [r for r in results if not r.ok]
    if failed:
        raise RenderError("; ".join(f"{r.name}: {r.detail}" for r in failed))
    return results
