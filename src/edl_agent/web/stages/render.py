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


def _combo_suffix(job: JobState) -> str:
    """Cache key for the current `hook_flash`/`punch_in` combo's preview.

    Only 4 combos exist, so each is cached under its own
    `preview_segments{suffix}`/`reel_preview{suffix}.mp4` -- toggling back
    to a combo already rendered this run skips straight to the pause
    instead of re-encoding.
    """
    return f"_h{int(job.hook_flash)}p{int(job.punch_in)}"


def _run_render_stage(
    session_dir: Path,
    job: JobState,
    resume: bool,
    edl: dict,
    manifest: dict,
    candidates: dict,  # noqa: ARG001 - kept for stable call signature
    slots: dict,  # noqa: ARG001 - kept for stable call signature
    selection: dict | None,  # noqa: ARG001 - kept for stable call signature
    selection_meta: dict,  # noqa: ARG001 - kept for stable call signature
    tonemap_chain: str,
) -> dict:
    """Run (or resume) the render stage, then always run the render checks.

    Studio flow never pauses here: the preview (`reel_preview{suffix}.mp4`,
    see `_combo_suffix`) is rendered first for progressive watching, then
    the full-resolution render proceeds with the same `hook_flash`/
    `punch_in` defaults. Toggling effects later goes through
    `POST .../effects`, which rebuilds the EDL and re-renders.

    Returns:
        The `edl` actually rendered, for `_run_variant_b_stage` to reuse.
    """
    reel_path = session_dir / "reel.mp4"
    if resume and reel_path.exists():
        job.stages["render"] = "done"
        return edl

    with job.running("render"):
        suffix = _combo_suffix(job)
        preview_reel = session_dir / f"reel_preview{suffix}.mp4"
        if not preview_reel.exists():
            job.detail["render"] = "rendering preview segments (0/0)"
            render_preview_segments(
                edl,
                manifest,
                session_dir,
                threads=THREADS,
                tonemap_chain=tonemap_chain,
                suffix=suffix,
                reuse=None,
                on_progress=lambda done, total: job.detail.__setitem__(
                    "render", f"rendering preview segments ({done}/{total})"
                ),
            )
            job.detail["render"] = "concatenating preview, mixing audio"
            concat_and_audio(
                edl, session_dir, threads=THREADS, preview=True, suffix=suffix
            )
        job.detail["render"] = ""
        job.notices.append(
            {
                "kind": "effects",
                "message": "Preview ready; effects default off, toggle anytime",
            }
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
        job.check_results = [
            str(r)
            for r in run_render_checks(
                edl, session_dir, preview_suffix=_combo_suffix(job)
            )
        ]

    return edl
