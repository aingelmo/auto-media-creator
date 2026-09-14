"""Orchestration of Layers 4+ (planner/edl) for a session, per #8.5."""

from __future__ import annotations

import json
from pathlib import Path

from edl_agent.edl import build_edl
from edl_agent.planner import DEFAULT_CONFIG, apply_color_match
from edl_agent.session._common import tonemap_chain_for_manifest


def run_planner(
    session_dir: Path,
    manifest: dict,
    candidates_json: dict,
    slots_json: dict,
    selection: dict | None = None,
    selection_meta: dict | None = None,
    threads: int = 4,
    config: dict | None = None,
) -> dict:
    """Run selection (LLM, optional) -> S-checks/fallback -> planner -> edl.json.

    Per #8.5. Writes `edl.json` to `session_dir`.

    Args:
        session_dir: Session directory to write `edl.json` to.
        manifest: Parsed `manifest.json` (see `ingest.build_manifest`).
        candidates_json: Parsed `candidates.json`, with a `candidates` key.
        slots_json: Parsed `slots.json`, with a `slots` key.
        selection: LLM selection dict (see `selector.selection_schema`), or
            `None` to rely entirely on the rules fallback (#8.6).
        selection_meta: Metadata dict from `selector.select` (`model`,
            `llm_attempts`, `llm_cost_usd`, etc.), or `None`.
        threads: ffmpeg thread count, forwarded to the planner/render steps.
        config: Overrides merged over `planner.DEFAULT_CONFIG`.

    Returns:
        The `edl.json` dict (see `edl.build_edl`).

    Raises:
        PlannerError: If a planner invariant is violated or a role has no
            admissible candidate.
    """
    session_dir = Path(session_dir)
    tonemap_chain = tonemap_chain_for_manifest(manifest)

    edl = build_edl(
        session_id=manifest["session_id"],
        manifest=manifest,
        candidates_json=candidates_json,
        slots_json=slots_json,
        selection=selection,
        selection_meta=selection_meta,
        threads=threads,
        tonemap_chain=tonemap_chain,
        config=config,
    )
    apply_color_match(edl, manifest, session_dir, {**DEFAULT_CONFIG, **(config or {})})
    with (session_dir / "edl.json").open("w") as f:
        json.dump(edl, f, indent=2, ensure_ascii=False)
    return edl
