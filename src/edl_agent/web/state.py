"""Shared in-process job registry and session-status helpers used by every router.

Job progress is tracked in an in-memory dict, so it does not survive a
server restart -- fine for a local, single-process, single-user tool.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException

from edl_agent.paths import SESSIONS_DIR
from edl_agent.web.jobs import STAGES, JobState

# Providers offered in the UI dropdown, deepseek first so it's the default
# selection; anthropic/gemini stay usable via PROVIDERS for non-UI callers
# (CLI/scripts pass --provider directly). Keep in sync with
# frontend/src/types.ts `Provider` and `web/pipeline.py:DEFAULT_MODELS`:
# adding a provider here needs the frontend type widened plus
# `npm run build` refreshed into `web/static/` (gitignored).
UI_PROVIDERS = ("deepseek", "ollama")

# Provider -> env var read by edl_agent.llm.get_client; gemini/ollama use
# SDK-default/no-auth flows not worth preflighting here.
PROVIDER_API_KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}

# session name -> JobState, for runs started by this process.
jobs: dict[str, JobState] = {}
lock = threading.Lock()


def session_status(name: str) -> str:
    """Derive a session's display status for the home page listing.

    Args:
        name: Session directory name under `SESSIONS_DIR`.

    Returns:
        `"failed"`/`"running"` if tracked in `jobs`, `"done"` if
        `reel.mp4` already exists on disk, `"new"` otherwise.
    """
    job = jobs.get(name)
    if job is not None:
        if job.error:
            return "failed"
        if not job.done:
            return "running"
    if (SESSIONS_DIR / name / "reel.mp4").exists():
        return "done"
    return "new"


def stage_statuses(name: str) -> dict[str, str]:
    """Per-stage status for a session's checklist, live job or disk fallback.

    Args:
        name: Session directory name under `SESSIONS_DIR`.

    Returns:
        Dict keyed by `STAGES`. If a live `JobState` is tracked, its
        `stages` dict is used directly. Otherwise (server restarted since
        the run), status is derived from which artifact files exist on
        disk: `"done"` if the stage's output file exists, `"pending"`
        otherwise -- a run from a previous process has no "running"/"failed"
        signal available.
    """
    job = jobs.get(name)
    if job is not None:
        return job.stages
    session_dir = SESSIONS_DIR / name
    artifact_by_stage = {
        "ingest": "manifest.json",
        "candidates": "candidates.json",
        "selection": "selection.json",
        "hooks": "hooks.json",
        "planner": "edl.json",
        "render": "reel.mp4",
        "checks": "reel.mp4",
    }
    return {
        stage: "done"
        if (session_dir / artifact_by_stage[stage]).exists()
        else "pending"
        for stage in STAGES
    }


HISTORY_LIMIT = 20


def append_history(name: str, entry: dict[str, Any]) -> None:
    """Append a regenerate-request record to a session's `history.jsonl`.

    Args:
        name: Session directory name under `SESSIONS_DIR`.
        entry: JSON-serialisable record; a UTC `ts` field is added.
    """
    path = SESSIONS_DIR / name / "history.jsonl"
    record = {"ts": datetime.now(UTC).isoformat(timespec="seconds"), **entry}
    with path.open("a") as f:
        f.write(json.dumps(record) + "\n")


def read_history(name: str) -> list[dict[str, Any]]:
    """Read a session's regenerate history, most recent first.

    Args:
        name: Session directory name under `SESSIONS_DIR`.

    Returns:
        Up to `HISTORY_LIMIT` records, newest first. Empty if none logged.
    """
    path = SESSIONS_DIR / name / "history.jsonl"
    if not path.exists():
        return []
    lines = path.read_text().splitlines()[-HISTORY_LIMIT:]
    return [json.loads(line) for line in reversed(lines)]


def total_cost_usd(name: str) -> float:
    """Sum a session's lifetime LLM cost from its `costs.jsonl` ledger.

    Unlike `selection_meta.json`/`hooks.json`'s `cost_usd` (only the latest
    run), this ledger (`selector.pricing.append_cost_entry`) is never
    cleared by a regenerate, so it covers every attempt ever made.

    Args:
        name: Session directory name under `SESSIONS_DIR`.

    Returns:
        Total USD cost; `0.0` if no calls have been logged yet.
    """
    path = SESSIONS_DIR / name / "costs.jsonl"
    if not path.exists():
        return 0.0
    return sum(json.loads(line)["cost_usd"] for line in path.read_text().splitlines())


def load_json(name: str, filename: str) -> dict:
    """Read and parse a session artifact JSON file, or 404.

    Args:
        name: Session directory name under `SESSIONS_DIR`.
        filename: File name within the session directory.

    Returns:
        Parsed JSON content.

    Raises:
        HTTPException: 404 if the file doesn't exist yet.
    """
    path = SESSIONS_DIR / name / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{filename} not found yet")
    return json.loads(path.read_text())


def job_payload(job: JobState | None) -> dict[str, Any] | None:
    """Serialise a `JobState` to JSON, or `None` if there is no live job.

    `JobState` itself is not JSON-serialisable (it holds a
    `threading.Event`), so every field the frontend needs is picked out
    explicitly here.

    Args:
        job: Live job tracked in `jobs`, or `None`.

    Returns:
        `None` if `job` is `None`, else a dict with the subset of
        `JobState` fields the session page reads.
    """
    if job is None:
        return None
    return {
        "stages": job.stages,
        "detail": job.detail,
        "done": job.done,
        "error": job.error,
        "awaiting_confirmation": job.awaiting_confirmation,
        "pause_kind": job.pause_kind,
        "check_results": job.check_results,
        "check_results_b": job.check_results_b,
        "unverified_sources": job.unverified_sources,
        "low_candidates": job.low_candidates,
        "hooks": job.hooks,
        "hook_slot": job.hook_slot,
        "hook_choice": job.hook_choice,
        "music_candidates": job.music_candidates,
        "punch_in": job.punch_in,
        "hook_flash": job.hook_flash,
        "notices": job.notices,
    }
