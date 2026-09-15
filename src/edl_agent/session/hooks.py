"""Orchestration of the hook-line generation call for a session, per #5.7."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from edl_agent.selection import build_selected
from edl_agent.selector import generate_hooks


def run_hooks(
    session_dir: Path,
    candidates_json: dict,
    slots_json: dict,
    selection: dict | None,
    theme: str,
    client: Any,  # noqa: ANN401 (duck-typed: google-genai Client or OllamaClient)
    model: str,
) -> dict:
    """Find the hook candidate the same way the planner will, then generate hook lines.

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

    Returns:
        `hooks.json` dict, as returned by `selector.generate_hooks`.
    """
    selected, _warnings, _fallback_roles = build_selected(
        candidates_json, slots_json, selection
    )
    candidates_by_id = {c["id"]: c for c in candidates_json["candidates"]}
    hook_entry = next(e for e in selected if e["role"] == "hook")
    candidate = candidates_by_id[hook_entry["candidate_id"]]
    exercise = hook_entry.get("exercise", "other")
    return generate_hooks(candidate, exercise, theme, client, model, Path(session_dir))
