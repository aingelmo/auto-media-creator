"""Orchestration of Layers 4+ (planner/edl) for a session, per #8.5."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from edl_agent.edl import build_edl
from edl_agent.ingest import sha256_file
from edl_agent.planner import DEFAULT_CONFIG, apply_color_match
from edl_agent.session._common import tonemap_chain_for_manifest


def load_brand(session_dir: Path) -> dict | None:
    """Read `session_dir/brand/brand.json` + its logo PNG (#6.8), or `None`.

    `brand.json` holds `logo` (session-relative, default `brand/logo.png`)
    and optional `handle`, `line`, `bg`, `fg`, `font`. Returns it with
    `logo_sha256`, `logo_w`, `logo_h` added; `None` if the JSON or the
    logo file is missing (brand layer off, no error).
    """
    path = session_dir / "brand" / "brand.json"
    if not path.is_file():
        return None
    brand = json.loads(path.read_text())
    logo = session_dir / brand.get("logo", "brand/logo.png")
    if not logo.is_file():
        return None
    with Image.open(logo) as im:
        w, h = im.size
    return {
        **brand,
        "logo": str(logo.relative_to(session_dir)),
        "logo_sha256": sha256_file(logo),
        "logo_w": w,
        "logo_h": h,
    }


def run_planner(
    session_dir: Path,
    manifest: dict,
    candidates_json: dict,
    slots_json: dict,
    selection: dict | None = None,
    selection_meta: dict | None = None,
    threads: int = 4,
    config: dict | None = None,
    out_name: str = "edl.json",
) -> dict:
    """Run selection (LLM, optional) -> S-checks/fallback -> planner -> edl.json.

    Per #8.5. Writes `out_name` to `session_dir`. Picks up the session
    brand from `session_dir/brand/` if present (see `load_brand`).

    Args:
        session_dir: Session directory to write `out_name` to.
        manifest: Parsed `manifest.json` (see `ingest.build_manifest`).
        candidates_json: Parsed `candidates.json`, with a `candidates` key.
        slots_json: Parsed `slots.json`, with a `slots` key.
        selection: LLM selection dict (see `selector.selection_schema`), or
            `None` to rely entirely on the rules fallback (#8.6).
        selection_meta: Metadata dict from `selector.select` (`model`,
            `llm_attempts`, `llm_cost_usd`, etc.), or `None`.
        threads: ffmpeg thread count, forwarded to the planner/render steps.
        config: Overrides merged over `planner.DEFAULT_CONFIG`.
        out_name: Filename to write the EDL to, under `session_dir`, for an
            A/B variant (e.g. `"edl_b.json"`) alongside the default output.

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
        brand=load_brand(session_dir),
    )
    apply_color_match(edl, manifest, session_dir, {**DEFAULT_CONFIG, **(config or {})})
    with (session_dir / out_name).open("w") as f:
        json.dump(edl, f, indent=2, ensure_ascii=False)
    return edl
