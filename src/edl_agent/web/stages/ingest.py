"""The `ingest` stage: music gate, proxy build, and beat-slot detection."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from edl_agent.session import DEFAULT_CACHE_DIR, run_ingest
from edl_agent.slots import slots_from_file
from edl_agent.web.jobs import THREADS, JobState
from edl_agent.web.stages.music import (
    MUSIC_MAX_DURATION_S,
    MUSIC_OFFSET_S,
    _find_music_track,
    _run_music_choice_pause,
)

if TYPE_CHECKING:
    from pathlib import Path


def _run_ingest_stage(
    session_dir: Path, job: JobState, resume: bool
) -> tuple[dict, dict]:
    """Run (or resume) the ingest stage without blocking pauses.

    The studio flow keeps only the `"music_choice"` money gate (before
    any LLM spend). Unverified proxies are auto-kept and recorded in
    `job.notices` instead of pausing (#4.3).

    Returns:
        `(manifest, slots)`.

    Raises:
        _JobCancelledError: If the operator declines the music gate.
    """
    manifest_path = session_dir / "manifest.json"
    slots_path = session_dir / "slots.json"
    if resume and manifest_path.exists() and slots_path.exists():
        job.stages["ingest"] = "done"
        return json.loads(manifest_path.read_text()), json.loads(
            slots_path.read_text()
        )

    track = _find_music_track(session_dir)
    music_offset_s = MUSIC_OFFSET_S
    music_duration_s = MUSIC_MAX_DURATION_S
    if track is not None:
        music_offset_s, music_duration_s = _run_music_choice_pause(
            session_dir, job, track, DEFAULT_CACHE_DIR
        )

    with job.running("ingest"):
        job.detail["ingest"] = "probing sources, building proxies"
        manifest = run_ingest(
            session_dir,
            threads=THREADS,
            music_offset_s=music_offset_s,
            music_max_duration_s=music_duration_s,
            cache_root=DEFAULT_CACHE_DIR,
        )
        job.detail["ingest"] = "cutting music, detecting beat slots"
        slots = slots_from_file(str(session_dir / "music" / "track_cut.wav"))
        slots_path.write_text(json.dumps(slots, indent=2, ensure_ascii=False))

    job.unverified_sources = [
        s["src"]
        for s in manifest["sources"]
        if s.get("type") == "video" and not s.get("proxy_verified", True)
    ]
    if job.unverified_sources:
        job.notices.append(
            {
                "kind": "verification",
                "message": (
                    f"{len(job.unverified_sources)} clip(s) kept "
                    "without proxy verification"
                ),
                "sources": list(job.unverified_sources),
            }
        )
    return manifest, slots
