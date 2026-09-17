"""Orchestration of the hook-line generation call for a session, per #5.7."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from edl_agent.selector import generate_hook_copy


def reel_context(
    edl: dict,
    candidates_by_id: dict,
    selection: dict | None,
) -> str:
    """Build a plain-text summary of the final, ordered reel, for the hook-copy prompt.

    Unlike the selector's ranked candidate list, this reads the EDL the
    planner actually built, so every clip it names is a clip the viewer
    will actually see, in the order they'll see it.

    Args:
        edl: EDL dict, as returned by `edl.build_edl` (or `planner.run_planner`).
            Reads `clips`, each `{slot, role, candidate_id, out_s, in_s}`;
            a synthetic slot (e.g. `end_card`, from `planner._split_end_card`)
            carries its role name as a placeholder `candidate_id` that isn't
            a real key of `candidates_by_id`, and is skipped here.
        candidates_by_id: Mapping `candidate_id -> candidate dict`. Reads
            `kp_speed_abs`.
        selection: Parsed LLM selection output (see
            `selector.selection_schema`), or `None`; reads `selected`
            (for each clip's `exercise`/`reason`) and `notes` if present.

    Returns:
        Plain-text summary: one numbered `role: exercise, duration,
        velocidad -- reason` line per clip in timeline order (skipping
        clips with no `candidate_id`, e.g. the end card), then the total
        clip/develop counts and the selector's `notes`.
    """
    by_id = {e["candidate_id"]: e for e in (selection or {}).get("selected", [])}
    lines = []
    n_clips = 0
    n_develop = 0
    for clip in edl.get("clips", []):
        cid = clip.get("candidate_id")
        if not cid or cid not in candidates_by_id:
            continue
        n_clips += 1
        if clip["role"] == "develop":
            n_develop += 1
        entry = by_id.get(cid, {})
        candidate = candidates_by_id.get(cid, {})
        speed = candidate.get("kp_speed_abs", 0.0)
        duration = clip["out_s"] - clip["in_s"]
        exercise = entry.get("exercise", "other")
        line = (
            f"{n_clips}. {clip['role']}: {exercise}, {duration:.1f}s, "
            f"velocidad {speed:.2f}"
        )
        reason = entry.get("reason")
        if reason:
            line += f" -- {reason}"
        lines.append(line)

    lines.append(f"clips: {n_clips} (develop: {n_develop})")

    notes = (selection or {}).get("notes")
    if notes:
        lines.append(f"notas del selector: {notes}")

    return "\n".join(lines)


def run_hooks(
    session_dir: Path,
    candidates_json: dict,
    edl: dict,
    selection: dict | None,
    theme: str,
    client: Any,  # noqa: ANN401 (duck-typed: google-genai Client or OllamaClient)
    model: str,
    hook_line_override: str = "",
    brief: str = "",
    audience: str = "prospects",
) -> dict:
    """Find the hook clip in the final EDL, then generate its copy.

    Args:
        session_dir: Session directory to write `hooks.json` to.
        candidates_json: Parsed `candidates.json`, with a `candidates` key.
        edl: EDL dict already built by the planner (e.g. with a placeholder
            hook line), so hooks are generated from the reel the viewer
            will actually see, in order.
        selection: LLM selection dict (see `selector.selection_schema`), or
            `None` if the fallback selected everything.
        theme: Selector prompt theme, a key of `selector.prompts.THEMES`.
        client: LLM client, as built by `edl_agent.llm.get_client`.
        model: Model name to call.
        hook_line_override: Operator-typed text; if non-empty, skips the LLM
            call entirely (see `selector.generate_hook_copy`).
        brief: Operator-typed session brief, passed through to
            `selector.generate_hook_copy`.
        audience: `"prospects"` or `"members"`, passed through to
            `selector.generate_hook_copy`.

    Returns:
        `hooks.json` dict, as returned by `selector.generate_hook_copy`.
    """
    candidates_by_id = {c["id"]: c for c in candidates_json["candidates"]}
    clips = [
        c for c in edl["clips"] if c.get("candidate_id") in candidates_by_id
    ]
    hook_clip = next(c for c in clips if c["role"] == "hook")
    candidate = candidates_by_id[hook_clip["candidate_id"]]
    by_id = {e["candidate_id"]: e for e in (selection or {}).get("selected", [])}
    exercise = by_id.get(hook_clip["candidate_id"], {}).get("exercise", "other")
    others = [
        candidates_by_id[c["candidate_id"]]
        for c in clips
        if c["candidate_id"] != hook_clip["candidate_id"]
    ]
    context = reel_context(edl, candidates_by_id, selection)
    return generate_hook_copy(
        candidate,
        exercise,
        theme,
        client,
        model,
        Path(session_dir),
        hook_line_override=hook_line_override,
        brief=brief,
        audience=audience,
        context=context,
        others=others,
    )
