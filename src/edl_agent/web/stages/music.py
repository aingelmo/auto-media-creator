"""The `"music_choice"` pause: picking which snippet of the track to use."""

from __future__ import annotations

from typing import TYPE_CHECKING

from edl_agent.ingest import cut_music, ffprobe, rank_highlights
from edl_agent.web.jobs import JobState, _JobCancelledError

if TYPE_CHECKING:
    from pathlib import Path

from edl_agent.session._common import MUSIC_EXTS

MUSIC_OFFSET_S = 15.0
MUSIC_MAX_DURATION_S = 15.0
MIN_SHORTEN_DURATION_S = 5.0
SHORTEN_ATTEMPTS = 4  # beat detection isn't linear in duration; try progressively
MUSIC_CANDIDATE_COUNT = 3


def _shorten_durations(start_s: float) -> list[float]:
    """Decreasing durations to try when shortening, from `start_s` down to minimum.

    Beat detection doesn't scale slot count linearly with duration, so a
    single guessed duration isn't reliable; each step is retried against the
    real slot count until one produces few enough slots (see the
    `"low_candidates"` pause in `run_pipeline_job`).
    """
    if start_s <= MIN_SHORTEN_DURATION_S:
        return [MIN_SHORTEN_DURATION_S]
    step = (start_s - MIN_SHORTEN_DURATION_S) / (SHORTEN_ATTEMPTS - 1)
    return [round(start_s - i * step, 1) for i in range(SHORTEN_ATTEMPTS)]


def _find_music_track(session_dir: Path) -> Path | None:
    """Return the session's music track file, if any."""
    music_dir = session_dir / "music"
    if not music_dir.is_dir():
        return None
    return next(
        (p for p in sorted(music_dir.iterdir()) if p.suffix.lower() in MUSIC_EXTS),
        None,
    )


def _probe_duration_s(path: Path) -> float:
    """Return a media file's duration in seconds, via ffprobe."""
    return float(ffprobe(path)["format"]["duration"])


def _generate_music_candidates(
    track: Path,
    out_dir: Path,
    session_dir: Path,
    already: int,
    duration_s: float,
    cache_root: Path | None,
    count: int = MUSIC_CANDIDATE_COUNT,
) -> list[dict]:
    """Cut the next `count` ranked candidate snippets, after `already` picked ones.

    Ranks every `window_s` offset in `track` by drop-detection heuristic
    (see `rank_highlights`), snapped to the nearest downbeat, and cuts ranks
    `[already, already + count)`. Falls back to evenly-spaced offsets if
    ranking fails or runs out.

    Returns:
        New candidate dicts (`{"offset_s", "path", "score"}`, `path`
        relative to `session_dir`), appended after `already` existing ones.
    """
    usable = duration_s - MUSIC_MAX_DURATION_S
    try:
        ranked = rank_highlights(
            track, MUSIC_MAX_DURATION_S, cache_root=cache_root
        )
    except Exception:  # noqa: BLE001 (any librosa/decode failure -> fallback)
        ranked = []
    batch = ranked[already : already + count]
    if len(batch) < count:
        total = already + count
        step = usable / max(total, 1)
        batch += [
            {"offset_s": round(step * i, 1), "score": None}
            for i in range(already + len(batch), total)
        ]

    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for i, cand in enumerate(batch):
        idx = already + i
        path = out_dir / f"cand_{idx}.wav"
        cut_music(track, path, cand["offset_s"], MUSIC_MAX_DURATION_S)
        results.append(
            {
                "offset_s": cand["offset_s"],
                "path": str(path.relative_to(session_dir)),
                "score": cand.get("score"),
            }
        )
    return results


def _run_music_choice_pause(
    session_dir: Path, job: JobState, track: Path, cache_root: Path | None
) -> float:
    """Pause for the operator to pick a music offset, per the `"music_choice"` pause.

    Generates batches of `MUSIC_CANDIDATE_COUNT` ranked candidate cuts (best
    first), accumulating them in `job.music_candidates` across "generate
    more" rounds so earlier batches stay pickable.

    Returns:
        The chosen offset, in seconds.

    Raises:
        _JobCancelledError: If the operator declines the pause.
    """
    duration_s = _probe_duration_s(track)
    if duration_s <= MUSIC_MAX_DURATION_S:
        return 0.0

    candidates_dir = session_dir / "music" / "candidates"
    job.music_candidates = []
    while True:
        new = _generate_music_candidates(
            track,
            candidates_dir,
            session_dir,
            len(job.music_candidates),
            duration_s,
            cache_root,
        )
        job.music_candidates += new

        job.pause_kind = "music_choice"
        job.awaiting_confirmation = True
        job.confirm_event.wait()
        job.confirm_event.clear()
        job.awaiting_confirmation = False
        if job.cancelled:
            raise _JobCancelledError
        if not job.more_music:
            return job.music_choice_offset
        job.more_music = False
