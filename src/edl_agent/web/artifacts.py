"""Deleting stage output so a resumed job redoes it."""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

from edl_agent.web.jobs import STAGES

if TYPE_CHECKING:
    from pathlib import Path

# Files/dirs (relative to a session dir) each stage writes, used by
# `clear_stage_artifacts` to force a stage to redo under `resume=True`.
# `ingest` is omitted: forcing it to redo also needs re-running the
# verification pause flow, which the regenerate form doesn't drive.
STAGE_ARTIFACTS = {
    "candidates": ["candidates.json"],
    "selection": ["selection.json", "selection_meta.json"],
    "hooks": ["hooks.json", "hook_previews"],
    "planner": ["edl.json", "edl_b.json"],
    "render": [
        "reel.mp4",
        "segments",
        "preview_segments",
        "reel_b.mp4",
        "segments_b",
        "preview_segments_b",
    ],
    "checks": [],
}


def clear_stage_artifacts(session_dir: Path, from_stage: str) -> None:
    """Delete `from_stage` and later stages' output so resume=True redoes them.

    Backs up an existing `reel.mp4` to `reel.prev.mp4` before deleting it.

    Args:
        session_dir: Session directory to clear artifacts in.
        from_stage: First stage (in `STAGES` order) to force a redo of.
    """
    reel_path = session_dir / "reel.mp4"
    if reel_path.exists():
        shutil.copy(reel_path, session_dir / "reel.prev.mp4")
    reel_b_path = session_dir / "reel_b.mp4"
    if reel_b_path.exists():
        shutil.copy(reel_b_path, session_dir / "reel_b.prev.mp4")

    for stage in STAGES[STAGES.index(from_stage) :]:
        for rel_path in STAGE_ARTIFACTS.get(stage, []):
            path = session_dir / rel_path
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)
