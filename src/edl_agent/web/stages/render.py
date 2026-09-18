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
    candidates: dict,
    slots: dict,
    selection: dict | None,
    selection_meta: dict,
    tonemap_chain: str,
) -> dict:
    """Run (or resume) the render stage, then always run the render checks.

    Pauses after each preview render with `pause_kind == "effects_preview"`
    so the operator can watch `reel_preview{suffix}.mp4` (see
    `_combo_suffix`) and decide on `hook_flash` and `punch_in` before
    paying for the full-resolution segment render.
    Toggling and resubmitting (`effects_preview_again`) rebuilds `edl` via
    `_build_final_edl` (new `hook_flash`/`punch_in`, same hook line/text
    config) and loops back to a fresh preview instead of proceeding.

    Each `hook_flash`/`punch_in` combo's preview is cached (see
    `_combo_suffix`): re-visiting one already rendered this run reuses the
    file on disk, and a fresh combo still hardlinks whichever clips are
    unaffected by the toggle from the previous combo's segments.

    Returns:
        The `edl` actually rendered -- unchanged unless `hook_flash` or
        `punch_in` was toggled during the pause -- for
        `_run_variant_b_stage` to reuse.
    """
    reel_path = session_dir / "reel.mp4"
    if resume and reel_path.exists():
        job.stages["render"] = "done"
        return edl

    with job.running("render"):
        prev_edl: dict | None = None
        prev_suffix = ""
        while True:
            suffix = _combo_suffix(job)
            preview_reel = session_dir / f"reel_preview{suffix}.mp4"
            if not preview_reel.exists():
                reuse = None
                if prev_edl is not None:
                    prev_by_slot = {c["slot"]: c for c in prev_edl["clips"]}
                    reuse = {
                        c["slot"]: session_dir
                        / f"preview_segments{prev_suffix}"
                        / f"seg_{c['slot']:02d}.mp4"
                        for c in edl["clips"]
                        if c == prev_by_slot.get(c["slot"])
                    }
                job.detail["render"] = "rendering preview segments (0/0)"
                render_preview_segments(
                    edl,
                    manifest,
                    session_dir,
                    threads=THREADS,
                    tonemap_chain=tonemap_chain,
                    suffix=suffix,
                    reuse=reuse,
                    on_progress=lambda done, total: job.detail.__setitem__(
                        "render", f"rendering preview segments ({done}/{total})"
                    ),
                )
                job.detail["render"] = "concatenating preview, mixing audio"
                concat_and_audio(
                    edl, session_dir, threads=THREADS, preview=True, suffix=suffix
                )
            job.detail["render"] = ""
            prev_edl, prev_suffix = edl, suffix

            job.pause_kind = "effects_preview"
            job.awaiting_confirmation = True
            job.confirm_event.wait()
            job.confirm_event.clear()
            job.awaiting_confirmation = False
            if job.cancelled:
                raise _JobCancelledError
            # Rebuild unconditionally (cheap: just run_planner, no ffmpeg) so
            # the final render always reflects whatever hook_flash/punch_in
            # was last submitted, even if the operator clicked "Render final
            # video" before an in-flight preview toggle's rebuild landed.
            job.detail["render"] = "rebuilding EDL"
            edl = _build_final_edl(
                session_dir, manifest, candidates, slots, selection, selection_meta, job
            )
            if not job.effects_preview_again:
                break
            job.effects_preview_again = False

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
