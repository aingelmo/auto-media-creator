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
MUSIC_MIN_DURATION_S = 8.0
MIN_SHORTEN_DURATION_S = 5.0
SHORTEN_ATTEMPTS = 4  # beat detection isn't linear in duration; try progressively
MUSIC_CANDIDATE_COUNT = 3


def clamp_preset_window(
    track_duration_s: float,
    offset_s: float,
    duration_s: float,
) -> tuple[float, float] | None:
    """Clamp a pinned music window into the musical range, per #4.3.

    Args:
        track_duration_s: Full track length in seconds, via ffprobe.
        offset_s: Pinned window start in seconds, from the new-session form.
        duration_s: Pinned window length in seconds, from the form.

    Returns:
        `(offset_s, duration_s)` clamped to `MUSIC_MIN_DURATION_S` to
        `MUSIC_MAX_DURATION_S` and inside `[0, track_duration_s]`, each
        rounded to 0.1s; `None` when the track is at most
        `MUSIC_MAX_DURATION_S` (short tracks bypass the music gate, so a
        pin carries no information).
    """
    if track_duration_s <= MUSIC_MAX_DURATION_S:
        return None
    dur = min(MUSIC_MAX_DURATION_S, max(MUSIC_MIN_DURATION_S, duration_s))
    off = min(max(0.0, offset_s), max(0.0, track_duration_s - dur))
    return (round(off, 1), round(dur, 1))


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

    Ranks joint (offset, duration) windows in `track` by drop energy
    plus phrase closure (see `rank_highlights`), snapped to the nearest
    downbeat with beat-quantized ends, and cuts ranks `[already,
    already + count)`. Falls back to evenly-spaced full-length offsets
    if ranking fails or runs out.

    Returns:
        New candidate dicts (`{"offset_s", "duration_s", "path",
        "score", "reason", "close_closure", "d_close_beat_s"}`, `path`
        relative to `session_dir`), appended after `already` existing ones.
    """
    usable = duration_s - MUSIC_MAX_DURATION_S
    try:
        ranked = rank_highlights(
            track,
            MUSIC_MAX_DURATION_S,
            min_window_s=MUSIC_MIN_DURATION_S,
            cache_root=cache_root,
        )
    except Exception:  # noqa: BLE001 (any librosa/decode failure -> fallback)
        ranked = []
    batch = ranked[already : already + count]
    if len(batch) < count:
        total = already + count
        step = usable / max(total, 1)
        batch += [
            {
                "offset_s": round(step * i, 1),
                "duration_s": MUSIC_MAX_DURATION_S,
                "score": None,
                "reason": None,
                "close_closure": None,
                "d_close_beat_s": None,
            }
            for i in range(already + len(batch), total)
        ]

    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for i, cand in enumerate(batch):
        idx = already + i
        path = out_dir / f"cand_{idx}.wav"
        cut_music(track, path, cand["offset_s"], cand["duration_s"])
        results.append(
            {
                "offset_s": cand["offset_s"],
                "duration_s": cand["duration_s"],
                "path": str(path.relative_to(session_dir)),
                "score": cand.get("score"),
                "reason": cand.get("reason"),
                "close_closure": cand.get("close_closure"),
                "d_close_beat_s": cand.get("d_close_beat_s"),
            }
        )
    return results


def _run_music_choice_pause(
    session_dir: Path, job: JobState, track: Path, cache_root: Path | None
) -> tuple[float, float]:
    """Pause for the operator to pick a music (offset, duration), per pause.

    Generates batches of `MUSIC_CANDIDATE_COUNT` ranked candidate cuts
    (best first), accumulating them in `job.music_candidates` across
    "generate more" rounds so earlier batches stay pickable. Candidates
    carry joint-selected durations (`MUSIC_MIN_DURATION_S` to
    `MUSIC_MAX_DURATION_S`), so the reel length follows the music's
    phrase closure instead of a fixed 15 s.

    Returns:
        `(offset_s, duration_s)` of the chosen cut, in seconds.

    Raises:
        _JobCancelledError: If the operator declines the pause.
    """
    duration_s = _probe_duration_s(track)
    if duration_s <= MUSIC_MAX_DURATION_S:
        return 0.0, MUSIC_MAX_DURATION_S

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
            return job.music_choice_offset, job.music_choice_duration
        job.more_music = False
