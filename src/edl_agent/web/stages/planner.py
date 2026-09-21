"""The `hooks` stage (manual-only, no LLM) and the `planner` stage."""

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


def _build_final_edl(
    session_dir: Path,
    manifest: dict,
    candidates: dict,
    slots: dict,
    selection: dict | None,
    selection_meta: dict,
    job: JobState,
) -> dict:
    """Build the final EDL for `job`'s current hook/flash/punch-in choices.

    Shared by `_run_hooks_and_planner_stage`'s post-hook-choice build and
    `_run_render_stage`'s punch-in preview loop (`stages/render.py`), so a
    `punch_in` toggle rebuilds with exactly the same hook config as the
    original build.
    """
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
            "punch_in": job.punch_in,
        },
    )


def _write_manual_hooks(
    session_dir: Path,
    base_edl: dict,
    job: JobState,
) -> dict:
    """Write a zero-cost `hooks.json` with no LLM candidates, per #5.7.

    The web UI only offers a manual hook line or none; automatic
    hook-copy generation stays available via `scripts/run_e2e.py`
    (and `session.run_hooks` directly) for calibration.

    Args:
        session_dir: Session directory to write `hooks.json` to.
        base_edl: Hookless preview EDL, as built by `run_planner`;
            reads `clips` to find the hook clip's `candidate_id`.
        job: Live job; reads `brief`/`audience` so the artifact keeps
            the operator context even though no LLM call is made.

    Returns:
        The `hooks.json` dict (`hooks == []`, `source == "manual"`).
    """
    hook_clip = next(c for c in base_edl["clips"] if c["role"] == "hook")
    result = {
        "candidate_id": hook_clip.get("candidate_id", ""),
        "hook_line": "",
        "hooks": [],
        "dropped": [],
        "evidence": [],
        "rejected": None,
        "source": "manual",
        "usage": None,
        "cost_usd": 0.0,
        "brief": job.brief,
        "audience": job.audience,
    }
    with (session_dir / "hooks.json").open("w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    return result


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
    """Run the manual-only hooks stage, then the planner stage.

    Never calls the hook-copy LLM: the hook line is either
    `job.hook_line_override` (regenerate form) or picked manually at
    the `hook_choice` pause (`""` = none). The automatic path stays
    available via `scripts/run_e2e.py` for calibration.

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
    # Build the reel once, with no hook text, so the hook-choice pause
    # previews the final, ordered clip list -- the reel the viewer will
    # actually see. This runs under the "planner" stage (not "hooks"), so
    # the UI reflects that reel planning happens before hook picking (#5.7).
    with job.running("planner"):
        job.detail["planner"] = "building preview EDL"
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

    if resume and hooks_path.exists():
        job.stages["hooks"] = "done"
        hooks = json.loads(hooks_path.read_text())
    else:
        with job.running("hooks"):
            if job.hook_line_override:
                job.detail["hooks"] = "applying manual hook line"
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
            else:
                job.detail["hooks"] = "manual hook choice (no LLM)"
                hooks = _write_manual_hooks(session_dir, base_edl, job)
    job.hooks = hooks
    preview_edl = base_edl
    job.detail["hooks"] = "rendering hook preview"
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

    with job.running("planner"):
        job.detail["planner"] = "building final EDL"
        return _build_final_edl(
            session_dir, manifest, candidates, slots, selection, selection_meta, job
        )
