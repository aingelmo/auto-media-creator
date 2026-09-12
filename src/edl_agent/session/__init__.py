"""Orchestration of Layer 1 and Layer 2 for a session.

Layout under sessions/<session_id>/ (see #1, #4).
"""

from __future__ import annotations

from pathlib import Path

from edl_agent.selector import select as selector_select
from edl_agent.session._common import IMAGE_EXTS, VIDEO_EXTS
from edl_agent.session.candidates import run_candidates
from edl_agent.session.ingest import run_ingest
from edl_agent.session.planner import run_planner
from edl_agent.slots import FRAME_RATE

__all__ = [
    "IMAGE_EXTS",
    "VIDEO_EXTS",
    "run_candidates",
    "run_ingest",
    "run_planner",
    "run_selection",
]


def run_selection(
    session_dir: Path,
    candidates_json: dict,
    slots_json: dict,
    config: dict | None = None,
    client: object | None = None,
) -> tuple[dict | None, dict]:
    """Call Layer 3 (LLM selector) with a real client, per #5.

    Args:
        session_dir: Session directory to write `selection_attempt_N.json`
            files to.
        candidates_json: Parsed `candidates.json`, with a `candidates` key.
        slots_json: Parsed `slots.json`, with `slots` and `duration_f` keys.
        config: Overrides merged over `selector.DEFAULTS`; see
            `selector.select`.
        client: LLM client to use; defaults to `google.genai.Client()`
            (API key via env `GEMINI_API_KEY`/`GOOGLE_API_KEY`). Pass
            `client=OllamaClient()` (`ollama_client.py`) to test locally
            before spending on Gemini.

    Returns:
        `(selection, selection_meta)`, as returned by `selector.select`.
    """
    if client is None:
        from google import genai

        client = genai.Client()

    duration_s = slots_json["duration_f"] / FRAME_RATE
    return selector_select(
        candidates_json, slots_json, duration_s, client, Path(session_dir), config
    )
