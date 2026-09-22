"""The `candidates` stage: feature extraction plus auto-shorten on scarcity."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from edl_agent.candidates import readmit_candidates
from edl_agent.features import free_torch_memory, yolo_pose_detector
from edl_agent.ingest import cut_music, sha256_file, write_manifest
from edl_agent.session import DEFAULT_CACHE_DIR, run_candidates
from edl_agent.slots import slots_from_file
from edl_agent.web.jobs import POSE_MODEL, JobState
from edl_agent.web.stages.music import (
    MIN_SHORTEN_DURATION_S,
    MUSIC_MAX_DURATION_S,
)

if TYPE_CHECKING:
    from pathlib import Path


def _shorten_to_fit(
    session_dir: Path, manifest: dict, slots: dict, job: JobState
) -> dict:
    """Re-cut the music shorter so slot count fits usable sources.

    Tries progressively shorter durations (see `music._shorten_durations`)
    until the slot count fits `real_sources`, keeping the fewest-slot
    result. Rewrites `manifest.json`/`slots.json` and readmits candidates.

    Args:
        session_dir: Session directory with `music/track_cut.wav`.
        manifest: Ingest manifest dict (mutated in place).
        slots: Current slots dict (replaced on success).
        job: Live job; reads `low_candidates["suggested_duration_s"]`.

    Returns:
        New slots dict.
    """
    from edl_agent.web.stages.music import _shorten_durations

    music = manifest["music"]
    cut_path = session_dir / "music" / "track_cut.wav"
    orig_track = session_dir / music["src"]

    best_duration, best_slots = None, None
    for new_duration in _shorten_durations(
        job.low_candidates["suggested_duration_s"]
    ):
        cut_music(orig_track, cut_path, music["offset_s"], new_duration)
        candidate_slots = slots_from_file(str(cut_path))
        if best_slots is None or len(candidate_slots["slots"]) < len(
            best_slots["slots"]
        ):
            best_duration, best_slots = new_duration, candidate_slots
        if len(candidate_slots["slots"]) <= job.low_candidates["real_sources"]:
            break

    if best_slots is None or best_duration is None:
        msg = "No valid slot duration found"
        raise RuntimeError(msg)

    if new_duration != best_duration:
        cut_music(orig_track, cut_path, music["offset_s"], best_duration)
    slots = best_slots

    music["max_duration_s"] = best_duration
    music["cut_sha256"] = sha256_file(cut_path)
    write_manifest(manifest, session_dir / "manifest.json")

    (session_dir / "slots.json").write_text(
        json.dumps(slots, indent=2, ensure_ascii=False)
    )
    return slots


def _run_candidates_stage(
    session_dir: Path, job: JobState, resume: bool, manifest: dict, slots: dict
) -> tuple[dict, dict]:
    """Run (or resume) the candidates stage, auto-shortening on scarcity.

    Studio flow never pauses here: when usable video sources are fewer
    than slots, the music is auto-recut shorter so the reel fits the
    footage, recording a `notices` entry instead of blocking (#4.3).

    Returns:
        `(candidates, slots)` -- `slots` may differ from the input if
        auto-shortened.
    """
    candidates_path = session_dir / "candidates.json"
    if resume and candidates_path.exists():
        job.stages["candidates"] = "done"
        return json.loads(candidates_path.read_text()), slots

    with job.running("candidates"):
        job.detail["candidates"] = "loading pose model"
        detector = yolo_pose_detector(POSE_MODEL)
        job.detail["candidates"] = "extracting features, detecting candidates"
        candidates = run_candidates(
            session_dir,
            manifest,
            slots,
            detector,
            pose_model_path=POSE_MODEL,
            cache_root=DEFAULT_CACHE_DIR,
        )
        # P0 light-device: torch holds ~3 GB resident after inference;
        # release before the LLM/render stages so their RSS is real.
        del detector
        free_torch_memory()

    real_sources = len(
        {
            c["src"]
            for c in candidates["candidates"]
            if c["kind"] != "image" and c["admits_slots"]
        }
    )
    slot_count = len(slots["slots"])
    has_video_sources = any(s.get("type") == "video" for s in manifest["sources"])
    if not (has_video_sources and real_sources < slot_count):
        return candidates, slots

    job.low_candidates = {
        "real_sources": real_sources,
        "slot_count": slot_count,
        "suggested_duration_s": max(
            MIN_SHORTEN_DURATION_S,
            round(MUSIC_MAX_DURATION_S * real_sources / slot_count, 1),
        ),
    }
    slots = _shorten_to_fit(session_dir, manifest, slots, job)
    job.notices.append(
        {
            "kind": "low_candidates",
            "message": (
                f"Auto-shortened to fit {real_sources} source(s) "
                f"into {len(slots['slots'])} slot(s)"
            ),
            "detail": dict(job.low_candidates),
        }
    )

    readmit_candidates(candidates["candidates"], slots["slots"])
    candidates_path.write_text(json.dumps(candidates, indent=2, ensure_ascii=False))

    return candidates, slots
