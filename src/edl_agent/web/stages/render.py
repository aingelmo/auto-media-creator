"""The `render` stage (variant A) and the always-run `checks` stage."""

from __future__ import annotations

from typing import TYPE_CHECKING

from edl_agent.render import (
    concat_and_audio,
    render_preview_segments,
    render_segments,
    run_render_checks,
)
from edl_agent.web.jobs import THREADS, JobState, _JobCancelledError
from edl_agent.web.stages.planner import _build_final_edl

if TYPE_CHECKING:
    from pathlib import Path


def _run_render_stage(
    session_dir: Path,
    job: JobState,
    resume: bool,
    edl: dict,
    manifest: dict,
    candidates: dict,
    slots: dict,
    selection: dict | None,
    selection_meta: dict,
    tonemap_chain: str,
) -> dict:
    """Run (or resume) the render stage, then always run the render checks.

    Pauses after each preview render with `pause_kind == "punch_preview"` so
    the operator can watch `reel_preview.mp4` and decide on `punch_in`
    before paying for the full-resolution segment render. Toggling and
    resubmitting (`punch_preview_again`) rebuilds `edl` via
    `_build_final_edl` (same hook/flash config, new `punch_in`) and loops
    back to a fresh preview instead of proceeding.

    Returns:
        The `edl` actually rendered -- unchanged unless `punch_in` was
        toggled during the pause -- for `_run_variant_b_stage` to reuse.
    """
    reel_path = session_dir / "reel.mp4"
    if resume and reel_path.exists():
        job.stages["render"] = "done"
        return edl

    with job.running("render"):
        while True:
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
            job.detail["render"] = "concatenating preview, mixing audio"
            concat_and_audio(edl, session_dir, threads=THREADS, preview=True)
            job.detail["render"] = ""

            job.pause_kind = "punch_preview"
            job.awaiting_confirmation = True
            job.confirm_event.wait()
            job.confirm_event.clear()
            job.awaiting_confirmation = False
            if job.cancelled:
                raise _JobCancelledError
            if not job.punch_preview_again:
                break
            job.punch_preview_again = False
            job.detail["render"] = "rebuilding EDL"
            edl = _build_final_edl(
                session_dir, manifest, candidates, slots, selection, selection_meta, job
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

    return edl
