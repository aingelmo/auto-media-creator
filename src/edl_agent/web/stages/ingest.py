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
    _probe_duration_s,
    _run_music_choice_pause,
    clamp_preset_window,
)

if TYPE_CHECKING:
    from pathlib import Path


def _run_ingest_stage(
    session_dir: Path,
    job: JobState,
    resume: bool,
    music_offset_s: float | None = None,
    music_duration_s: float | None = None,
) -> tuple[dict, dict]:
    """Run (or resume) the ingest stage without blocking pauses.

    The studio flow keeps only the `"music_choice"` money gate (before
    any LLM spend). Unverified proxies are auto-kept and recorded in
    `job.notices` instead of pausing (#4.3). A pinned window from the
    new-session form (`music_offset_s`/`music_duration_s`) skips the
    pause entirely once clamped into the musical range.

    Args:
        session_dir: Session directory with `inputs/` and `music/`.
        job: `JobState` updated in place for status polling.
        resume: Skip the stage when `manifest.json` and `slots.json`
            already exist on disk.
        music_offset_s: Pinned window start in seconds, or `None` for
            the auto-cut pause.
        music_duration_s: Pinned window length in seconds, or `None`.

    Returns:
        `(manifest, slots)` dicts from `run_ingest` and `slots_from_file`.

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
    offset_s = MUSIC_OFFSET_S
    duration_s = MUSIC_MAX_DURATION_S
    if track is not None:
        use_preset = False
        if music_offset_s is not None and music_duration_s is not None:
            try:
                track_dur = _probe_duration_s(track)
            except Exception:  # noqa: BLE001 - probe failure falls back
                track_dur = 0.0
            if track_dur > 0:
                use_preset = True
                preset = clamp_preset_window(
                    track_dur, music_offset_s, music_duration_s
                )
                if preset is None:
                    offset_s, duration_s = 0.0, MUSIC_MAX_DURATION_S
                else:
                    offset_s, duration_s = preset
                    job.notices.append(
                        {
                            "kind": "music_pin",
                            "message": (
                                f"pinned music {offset_s:.1f}s-"
                                f"{offset_s + duration_s:.1f}s, "
                                "skipped auto cuts"
                            ),
                        }
                    )
        if not use_preset:
            offset_s, duration_s = _run_music_choice_pause(
                session_dir, job, track, DEFAULT_CACHE_DIR
            )

    with job.running("ingest"):
        job.detail["ingest"] = "probing sources, building proxies"
        manifest = run_ingest(
            session_dir,
            threads=THREADS,
            music_offset_s=offset_s,
            music_max_duration_s=duration_s,
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
