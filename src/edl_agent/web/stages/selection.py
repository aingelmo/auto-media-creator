"""The `selection` stage: LLM clip selection."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from edl_agent.llm import get_client
from edl_agent.session import run_selection

if TYPE_CHECKING:
    from pathlib import Path

    from edl_agent.web.jobs import JobState


def _run_selection_stage(
    session_dir: Path,
    job: JobState,
    resume: bool,
    candidates: dict,
    slots: dict,
    provider: str,
    model: str,
    theme: str,
) -> tuple[dict | None, dict]:
    """Run (or resume) the selection stage.

    Returns:
        `(selection, selection_meta)`.
    """
    selection_path = session_dir / "selection.json"
    selection_meta_path = session_dir / "selection_meta.json"
    if resume and selection_path.exists():
        job.stages["selection"] = "done"
        selection = json.loads(selection_path.read_text()) or None
        selection_meta = (
            json.loads(selection_meta_path.read_text())
            if selection_meta_path.exists()
            else {}
        )
        return selection, selection_meta

    with job.running("selection"):
        job.detail["selection"] = f"calling {provider} for clip selection"
        client = get_client(provider)
        selection, selection_meta = run_selection(
            session_dir,
            candidates,
            slots,
            config={"model": model, "theme": theme},
            client=client,
        )
        selection_path.write_text(
            json.dumps(selection or {}, indent=2, ensure_ascii=False)
        )
        selection_meta_path.write_text(
            json.dumps(selection_meta or {}, indent=2, ensure_ascii=False)
        )
    return selection, selection_meta
