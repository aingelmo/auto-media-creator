"""Background pipeline runner for the web UI, mirroring scripts/run_e2e.py.

Orchestrates the per-stage modules under `edl_agent.web.stages`. Re-exports
`JobState` and `clear_stage_artifacts` so `edl_agent.web.pipeline` stays the
public entry point `app.py` and `scripts/*.py` import from.
"""

from __future__ import annotations

import traceback
from typing import TYPE_CHECKING

from edl_agent.session import tonemap_chain_for_manifest
from edl_agent.web.artifacts import clear_stage_artifacts
from edl_agent.web.jobs import STAGES, JobState, _JobCancelledError
from edl_agent.web.stages.candidates import _run_candidates_stage
from edl_agent.web.stages.ingest import _run_ingest_stage
from edl_agent.web.stages.planner import _run_hooks_and_planner_stage
from edl_agent.web.stages.render import _run_render_stage
from edl_agent.web.stages.selection import _run_selection_stage
from edl_agent.web.stages.variant_b import _run_variant_b_stage

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "DEFAULT_MODELS",
    "STAGES",
    "JobState",
    "clear_stage_artifacts",
    "run_pipeline_job",
]

DEFAULT_MODELS = {
    "gemini": "gemini-3.8-flash",
    "anthropic": "claude-sonnet-5",
    "deepseek": "deepseek-flash",
    "ollama": "qwen3-vl:8b-instruct",
}


def run_pipeline_job(
    session_dir: Path,
    provider: str,
    model: str,
    job: JobState,
    resume: bool = False,
    theme: str = "training",
    hook_line_override: str = "",
    brief: str = "",
    audience: str = "prospects",
) -> None:
    """Run the full ingest->render pipeline for a session, updating `job` along the way.

    Mirrors `scripts/run_e2e.py`'s `main()`, using the same fixed defaults
    for threads/pose-model/music-cut/tonemap since the web form only
    exposes session media and LLM provider/model.

    Args:
        session_dir: Session directory, already populated with `inputs/`
            and `music/track.<mp3|wav>` by the upload handler.
        provider: LLM provider name, one of `edl_agent.llm.PROVIDERS`.
        model: LLM model name for `provider`.
        job: `JobState` instance to update in place; the caller keeps a
            reference to it for status polling.
        resume: If `True`, skip any stage whose output file already exists
            on disk (loading it instead), per `/sessions/{name}/retry`.
        theme: Selector prompt theme, a key of `edl_agent.selector.prompts.THEMES`.
        hook_line_override: Operator-typed hook text from the new-session
            form; if non-empty, the `hooks` stage skips its LLM call.
        brief: Operator-typed session brief from the new-session form.
        audience: `"prospects"` | `"members"`, from the new-session form.
    """
    job.provider = provider
    job.model = model
    job.theme = theme
    job.hook_line_override = hook_line_override
    job.brief = brief
    job.audience = audience
    try:
        manifest, slots = _run_ingest_stage(session_dir, job, resume)
        candidates, slots = _run_candidates_stage(
            session_dir, job, resume, manifest, slots
        )
        selection, selection_meta = _run_selection_stage(
            session_dir, job, resume, candidates, slots, provider, model, theme
        )
        tonemap_chain = tonemap_chain_for_manifest(manifest)
        edl = _run_hooks_and_planner_stage(
            session_dir,
            job,
            resume,
            provider,
            model,
            theme,
            manifest,
            candidates,
            slots,
            selection,
            selection_meta,
            tonemap_chain,
        )
        _run_render_stage(session_dir, job, resume, edl, manifest, tonemap_chain)
        _run_variant_b_stage(
            session_dir,
            job,
            manifest,
            candidates,
            slots,
            selection,
            selection_meta,
            edl,
            tonemap_chain,
        )
    except _JobCancelledError:
        pass
    except Exception:  # noqa: BLE001 - surfaced to the status page, not swallowed
        job.error = traceback.format_exc()
    finally:
        job.done = True
