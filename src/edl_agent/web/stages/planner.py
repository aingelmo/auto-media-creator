"""The `hooks` stage (looping on retries) and the `planner` stage."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from edl_agent.llm import get_client
from edl_agent.render import render_hook_previews
from edl_agent.selection.s_checks import clean_hook_line
from edl_agent.session import run_hooks, run_planner
from edl_agent.web.jobs import THREADS, JobState, _JobCancelledError

if TYPE_CHECKING:
    from pathlib import Path


def _run_hooks_and_planner_stage(
    session_dir: Path,
    job: JobState,
    resume: bool,
    provider: str,
    model: str,
    theme: str,
    manifest: dict,
    candidates: dict,
    slots: dict,
    selection: dict | None,
    selection_meta: dict,
    tonemap_chain: str,
) -> dict:
    """Run (or resume) the hooks stage (looping on retries), then the planner stage.

    Returns:
        Final `edl` dict.

    Raises:
        _JobCancelledError: If the operator declines the hook-choice pause.
    """
    edl_path = session_dir / "edl.json"
    if resume and edl_path.exists():
        job.stages["hooks"] = "done"
        job.stages["planner"] = "done"
        return json.loads(edl_path.read_text())

    hooks_path = session_dir / "hooks.json"
    # Build the reel once, with no hook text, so hook-copy generation (#5.7)
    # can be fed the final, ordered clip list -- the reel the viewer will
    # actually see -- instead of the selector's pre-planning candidate pool.
    job.detail["hooks"] = "building preview EDL"
    base_edl = run_planner(
        session_dir,
        manifest,
        candidates,
        slots,
        selection,
        selection_meta,
        threads=THREADS,
        config={"hook_line_override": ""},
        out_name="edl_base.json",
    )
    job.hook_slot = next(c["slot"] for c in base_edl["clips"] if c["role"] == "hook")

    while True:
        if resume and hooks_path.exists() and not job.more_hooks:
            job.stages["hooks"] = "done"
            hooks = json.loads(hooks_path.read_text())
        else:
            with job.running("hooks"):
                job.detail["hooks"] = f"calling {provider} for hook line"
                client = get_client(provider)
                hooks = run_hooks(
                    session_dir,
                    candidates,
                    base_edl,
                    selection,
                    theme,
                    client,
                    model,
                    hook_line_override=job.hook_line_override,
                    brief=job.brief,
                    audience=job.audience,
                )
        job.hooks = hooks
        preview_edl = base_edl
        job.detail["hooks"] = "rendering hook line previews"
        render_hook_previews(
            preview_edl,
            manifest,
            session_dir,
            [h["hook_line"] for h in hooks["hooks"] if h["hook_line"]],
            THREADS,
            tonemap_chain,
        )
        job.detail["hooks"] = ""

        job.pause_kind = "hook_choice"
        job.awaiting_confirmation = True
        job.confirm_event.wait()
        job.confirm_event.clear()
        job.awaiting_confirmation = False
        if job.cancelled:
            raise _JobCancelledError
        if not job.more_hooks:
            break
        job.more_hooks = False

    with job.running("planner"):
        job.detail["planner"] = "building final EDL"
        return run_planner(
            session_dir,
            manifest,
            candidates,
            slots,
            selection,
            selection_meta,
            threads=THREADS,
            config={
                "hook_line_override": clean_hook_line(job.hook_choice),
                "hook_text": bool(clean_hook_line(job.hook_choice)),
                "hook_flash": job.hook_flash,
            },
        )
