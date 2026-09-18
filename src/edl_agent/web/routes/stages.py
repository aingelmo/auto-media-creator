"""Per-stage debug views: ingest, candidates, selection, planner."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from edl_agent.paths import SESSIONS_DIR
from edl_agent.web.state import load_json

router = APIRouter()


@router.get("/api/sessions/{name}/ingest")
def ingest_page(name: str) -> dict:
    """`manifest.json`'s sources for debugging the ingest stage."""
    return load_json(name, "manifest.json")


@router.get("/api/sessions/{name}/candidates")
def candidates_page(name: str) -> dict:
    """`candidates.json` with thumbnail URLs for debugging selection input."""
    payload = load_json(name, "candidates.json")
    candidates = payload["candidates"]
    for c in candidates:
        # peak_frames always live flat under session_dir/peaks/ (see
        # candidates/frames.py); use the filename rather than the stored
        # absolute path, which may be stale if SESSIONS_DIR has moved since
        # the candidate was built.
        c["peak_urls"] = [
            f"/sessions/{name}/files/peaks/{Path(jpg).name}" for jpg in c["peak_frames"]
        ]
    return {"candidates": candidates}


@router.get("/api/sessions/{name}/selection")
def selection_page(name: str) -> dict:
    """Every `selection_attempt_N.json` -- prompt, raw LLM reply, usage, cost."""
    session_dir = SESSIONS_DIR / name
    attempts = sorted(session_dir.glob("selection_attempt_*.json"))
    if not attempts:
        raise HTTPException(status_code=404, detail="no selection attempts yet")
    return {"attempts": [json.loads(p.read_text()) for p in attempts]}


@router.get("/api/sessions/{name}/hooks")
def hooks_page(name: str) -> dict:
    """`hooks.json` for debugging the hook-line stage."""
    return load_json(name, "hooks.json")


@router.get("/api/sessions/{name}/planner")
def planner_page(name: str) -> dict:
    """`edl.json`'s clip list for debugging the planner stage."""
    return load_json(name, "edl.json")
