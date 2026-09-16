"""Orchestration of the hook-line generation call for a session, per #5.7."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from edl_agent.selection import build_selected
from edl_agent.selector import generate_hook_copy


def selection_context(
    selected: list[dict],
    candidates_by_id: dict,
    slots_json: dict,
    selection: dict | None,
) -> str:
    """Build a plain-text summary of the whole selection, for the hook-copy prompt.

    Args:
        selected: Selection entries (see `selection.build_selected`), each
            reading `role`, `candidate_id`, `exercise`, and `reason` (if
            LLM-derived).
        candidates_by_id: Mapping `candidate_id -> candidate dict`. Reads
            `kind`, `kp_speed_abs`, `multi_subject`.
        slots_json: Parsed `slots.json`; reads `duration_f` (at 30fps).
        selection: Parsed LLM selection output (see
            `selector.selection_schema`), or `None`; reads `notes` if
            present.

    Returns:
        Plain-text summary: one `role: exercise (kind, velocidad)` line per
        selected clip in `selected` order, then a "grupo" line if any clip
        is `multi_subject`, the reel duration, and the selector's `notes`.
    """
    lines = []
    for entry in selected:
        candidate = candidates_by_id.get(entry["candidate_id"], {})
        speed = candidate.get("kp_speed_abs", 0.0)
        kind = candidate.get("kind", "?")
        exercise = entry.get("exercise", "other")
        line = f"{entry['role']}: {exercise} ({kind}, velocidad {speed:.2f})"
        reason = entry.get("reason")
        if reason:
            line += f" -- {reason}"
        lines.append(line)

    if any(
        candidates_by_id.get(e["candidate_id"], {}).get("multi_subject")
        for e in selected
    ):
        lines.append("grupo: sí, algún clip con varios atletas")

    duration_s = slots_json.get("duration_f", 0) / 30
    lines.append(f"duración del reel: {duration_s:.1f}s")

    notes = (selection or {}).get("notes")
    if notes:
        lines.append(f"notas del selector: {notes}")

    return "\n".join(lines)


def run_hooks(
    session_dir: Path,
    candidates_json: dict,
    slots_json: dict,
    selection: dict | None,
    theme: str,
    client: Any,  # noqa: ANN401 (duck-typed: google-genai Client or OllamaClient)
    model: str,
    hook_line_override: str = "",
    brief: str = "",
    audience: str = "prospects",
) -> dict:
    """Find the hook candidate the same way the planner will, then generate its copy.

    Args:
        session_dir: Session directory to write `hooks.json` to.
        candidates_json: Parsed `candidates.json`, with a `candidates` key.
        slots_json: Parsed `slots.json`, with a `slots` key.
        selection: LLM selection dict (see `selector.selection_schema`), or
            `None` to rely on the rules fallback to find the hook
            candidate.
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
    selected, _warnings, _fallback_roles = build_selected(
        candidates_json, slots_json, selection
    )
    candidates_by_id = {c["id"]: c for c in candidates_json["candidates"]}
    hook_entry = next(e for e in selected if e["role"] == "hook")
    candidate = candidates_by_id[hook_entry["candidate_id"]]
    exercise = hook_entry.get("exercise", "other")
    context = selection_context(selected, candidates_by_id, slots_json, selection)
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
    )
