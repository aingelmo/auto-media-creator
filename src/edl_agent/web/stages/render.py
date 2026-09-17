"""The `render` stage (variant A) and the always-run `checks` stage."""

from __future__ import annotations

from typing import TYPE_CHECKING

from edl_agent.render import (
    concat_and_audio,
    render_preview_segments,
    render_segments,
    run_render_checks,
)
from edl_agent.web.jobs import THREADS, JobState

if TYPE_CHECKING:
    from pathlib import Path


def _run_render_stage(
    session_dir: Path,
    job: JobState,
    resume: bool,
    edl: dict,
    manifest: dict,
    tonemap_chain: str,
) -> None:
    """Run (or resume) the render stage, then always run the render checks."""
    reel_path = session_dir / "reel.mp4"
    if resume and reel_path.exists():
        job.stages["render"] = "done"
    else:
        with job.running("render"):
            job.detail["render"] = "rendering preview segments (0/0)"
            render_preview_segments(
                edl,
                manifest,
                session_dir,
                threads=THREADS,
                tonemap_chain=tonemap_chain,
                on_progress=lambda done, total: job.detail.__setitem__(
                    "render", f"rendering preview segments ({done}/{total})"
                ),
            )
            job.detail["render"] = "rendering final segments (0/0)"
            render_segments(
                edl,
                manifest,
                session_dir,
                threads=THREADS,
                tonemap_chain=tonemap_chain,
                on_progress=lambda done, total: job.detail.__setitem__(
                    "render", f"rendering final segments ({done}/{total})"
                ),
            )
            job.detail["render"] = "concatenating segments, mixing audio"
            concat_and_audio(edl, session_dir, threads=THREADS)

    with job.running("checks"):
        job.detail["checks"] = "verifying rendered reel"
        job.check_results = [str(r) for r in run_render_checks(edl, session_dir)]
