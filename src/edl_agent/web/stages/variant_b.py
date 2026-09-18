"""Hook variant B (idea #7): render, mix, and check a second hook line."""

from __future__ import annotations

from typing import TYPE_CHECKING

from edl_agent.render import (
    concat_and_audio,
    render_preview_segments,
    render_segments,
    run_render_checks,
)
from edl_agent.selection.s_checks import clean_hook_line
from edl_agent.session import run_planner
from edl_agent.web.jobs import THREADS, JobState

if TYPE_CHECKING:
    from pathlib import Path


def _run_variant_b_stage(
    session_dir: Path,
    job: JobState,
    manifest: dict,
    candidates: dict,
    slots: dict,
    selection: dict | None,
    selection_meta: dict,
    edl: dict,
    tonemap_chain: str,
) -> None:
    """Render, mix, and check hook variant B (idea #7), if the operator chose one.

    Reuses A's segment files for every clip whose dict is identical in B
    (only the hook slot differs), so B costs one segment render.
    """
    hook_line_b = clean_hook_line(job.hook_choice_b)
    if not hook_line_b:
        return

    with job.running("render"):
        job.detail["render"] = "building variant B EDL"
        edl_b = run_planner(
            session_dir,
            manifest,
            candidates,
            slots,
            selection,
            selection_meta,
            threads=THREADS,
            config={
                "hook_line_override": hook_line_b,
                "hook_text": True,
                "peak_beat_index": 2,
                "hook_flash": job.hook_flash,
                "punch_in": job.punch_in,
            },
            out_name="edl_b.json",
        )
        clips_b_by_slot = {c["slot"]: c for c in edl_b["clips"]}
        reuse_final = {
            c["slot"]: session_dir / "segments" / f"seg_{c['slot']:02d}.mp4"
            for c in edl["clips"]
            if c == clips_b_by_slot.get(c["slot"])
        }
        reuse_preview = {
            c["slot"]: session_dir / "preview_segments" / f"seg_{c['slot']:02d}.mp4"
            for c in edl["clips"]
            if c == clips_b_by_slot.get(c["slot"])
        }
        job.detail["render"] = "rendering variant B preview segments"
        render_preview_segments(
            edl_b,
            manifest,
            session_dir,
            threads=THREADS,
            tonemap_chain=tonemap_chain,
            suffix="_b",
            reuse=reuse_preview,
        )
        job.detail["render"] = "rendering variant B final segments"
        render_segments(
            edl_b,
            manifest,
            session_dir,
            threads=THREADS,
            tonemap_chain=tonemap_chain,
            suffix="_b",
            reuse=reuse_final,
        )
        job.detail["render"] = "concatenating variant B, mixing audio"
        concat_and_audio(edl_b, session_dir, threads=THREADS, suffix="_b")

    with job.running("checks"):
        job.detail["checks"] = "verifying variant B reel"
        job.check_results_b = [
            str(r) for r in run_render_checks(edl_b, session_dir, suffix="_b")
        ]
