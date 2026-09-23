"""Rank candidate music windows by drop energy plus closing quality, per #3.5.

Scores every window start offset in a track on energy, onset flux, and
energy contrast (the jump that marks an EDM/trap drop), then snaps the
best offsets to the track's downbeat so a chosen clip opens on beat 1.
The window length is joint-selected, not fixed: for each snapped open,
every beat-quantized end between `min_window_s` and `window_s` is scored
by closure (sustained energy before the boundary times post-boundary
decay — a phrase ending, not a mid-sustain cutoff), and the best end
wins. Fixed-window callers pass `min_window_s == window_s` and get the
single nudged end instead. Results are cached per-track
(content-addressed, alongside proxy/feature caches) since sessions reuse
the same music across runs.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np

from edl_agent.ingest._common import sha256_file
from edl_agent.ingest.cache import atomic_write_text, source_cache_dir
from edl_agent.ingest.media import cut_music

CACHE_VERSION = 3
SAMPLE_RATE = 22050
HOP_LENGTH = 512
STEP_S = 0.25  # candidate start offsets are scored every quarter second
INTRO_SKIP_FRAC = 0.15
OUTRO_MARGIN_FRAC = 0.05
CONTRAST_WINDOW_S = 4.0
# Detect the jump over the full window (robust to a single spurious spike),
# but anchor the clip partway into it so playback starts on solid ground
# rather than the raw transition edge.
ANCHOR_SHIFT_S = CONTRAST_WINDOW_S / 2
ENERGY_WEIGHT = 0.3
FLUX_WEIGHT = 0.2
CONTRAST_WEIGHT = 0.5
KEEP_TOP = 12
# Joint (offset, duration) scoring stays open-dominant: the final score
# blends the open drop score with the normalized closure of the chosen
# end. Closure covers what the old off-beat/rising/weak malus did —
# rising-into-the-cut scores ~0 decay, weak passages score low pre-energy
# — while beat-quantized ends solve alignment structurally.
OPEN_MIX = 0.65
END_MIX = 0.35
END_SNAP_MAX_S = 0.15  # max start shift applied to land a fixed end on a beat
CLOSE_BEAT_WINDOW_S = 0.25  # fallback end-to-beat gap at/above this is full
CLOSE_BEAT_PENALTY_W = 0.5  # weight of that gap against a fallback end
CLOSE_PRE_S = 3.0  # sustained-energy window before a candidate end
CLOSE_POST_S = 1.0  # decay window after a candidate end
CLOSE_POOL_MULT = 3  # end-rescore this multiple of KEEP_TOP open-ranked


def rank_highlights(
    track: Path,
    window_s: float,
    *,
    cache_root: Path | None = None,
    min_window_s: float | None = None,
) -> list[dict]:
    """Rank candidate music windows in `track`, best first, per #3.5.

    Args:
        track: Path to the music file.
        window_s: Maximum length of the highlight window, in seconds.
        cache_root: If given, cache the ranking under
            `cache_root/<sha256 of track>/music_highlights.json` and reuse
            it on a later call with the same `track`/`window_s`/
            `min_window_s`.
        min_window_s: Minimum window length, in seconds (joint
            offset/duration selection over `[min_window_s, window_s]`).
            Defaults to `window_s` (fixed-length ranking).

    Returns:
        Ranked list of dicts (best first), each with `offset_s` (float,
        snapped to the downbeat), `duration_s` (float, joint-selected;
        `== window_s` when `min_window_s == window_s`), `end_s` (float,
        `offset_s + duration_s`, on a beat except the fixed-window
        fallback beyond nudge range), `score` (float, 0..1, open/close
        blend), `reason` (str, dominant open component),
        `d_close_beat_s` (float | None, residual end-to-beat gap;
        `None` when no beats were detected) and `close_closure`
        (float, raw closure of the chosen end).
    """
    if min_window_s is None or min_window_s > window_s:
        min_window_s = window_s
    cache_path = None
    if cache_root is not None:
        cache_path = source_cache_dir(cache_root, sha256_file(track)) / (
            "music_highlights.json"
        )
        cached = _read_cache(cache_path, window_s, min_window_s)
        if cached is not None:
            return cached

    ranked = _rank(track, window_s, min_window_s)

    if cache_path is not None:
        atomic_write_text(
            cache_path,
            json.dumps(
                {
                    "version": CACHE_VERSION,
                    "window_s": window_s,
                    "min_window_s": min_window_s,
                    "ranked": ranked,
                }
            ),
        )
    return ranked


def _read_cache(
    cache_path: Path, window_s: float, min_window_s: float
) -> list[dict] | None:
    if not cache_path.exists():
        return None
    data = json.loads(cache_path.read_text())
    if (
        data.get("version") != CACHE_VERSION
        or data.get("window_s") != window_s
        or data.get("min_window_s", data.get("window_s")) != min_window_s
    ):
        return None
    return data["ranked"]


def _rank(track: Path, window_s: float, min_window_s: float) -> list[dict]:
    import librosa

    # librosa's soundfile backend can't decode AAC/MP4 (or other
    # non-libsndfile) sources, so decode the full track via ffmpeg first.
    with tempfile.TemporaryDirectory() as tmp:
        wav_path = cut_music(track, Path(tmp) / "decoded.wav", 0.0, 1e6)
        y, sr = librosa.load(wav_path, sr=SAMPLE_RATE, mono=True)
    dur = len(y) / sr
    if dur <= window_s:
        return []

    rms = librosa.feature.rms(y=y, hop_length=HOP_LENGTH)[0]
    onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=HOP_LENGTH)
    frame_rate = sr / HOP_LENGTH

    lo, hi = INTRO_SKIP_FRAC * dur, dur - window_s - OUTRO_MARGIN_FRAC * dur
    if hi <= lo:
        lo, hi = 0.0, dur - window_s

    window_frames = round(window_s * frame_rate)
    contrast_frames = round(CONTRAST_WINDOW_S * frame_rate)
    step_frames = max(1, round(STEP_S * frame_rate))
    starts = range(round(lo * frame_rate), round(hi * frame_rate) + 1, step_frames)

    def contrast_at(t: int) -> float:
        pre = rms[max(0, t - contrast_frames) : t]
        pre_mean = float(np.mean(pre)) if len(pre) else 0.0
        return float(np.mean(rms[t : t + contrast_frames])) - pre_mean

    candidates = [
        {
            "start_frame": t,
            "energy": float(np.mean(rms[t : t + window_frames])),
            "flux": float(np.mean(onset_env[t : t + window_frames])),
            "contrast": contrast_at(t),
        }
        for t in starts
    ]
    if not candidates:
        return []

    for key in ("energy", "flux", "contrast"):
        _normalize(candidates, key)
    for c in candidates:
        c["score"] = (
            ENERGY_WEIGHT * c["energy"]
            + FLUX_WEIGHT * c["flux"]
            + CONTRAST_WEIGHT * c["contrast"]
        )
    candidates.sort(key=lambda c: c["score"], reverse=True)

    beat_frames = _beat_frames(y, sr)
    downbeats = _downbeat_frames(beat_frames, onset_env)
    beats_s = sorted(b / frame_rate for b in beat_frames)
    track_mean = float(np.mean(rms))

    pool = candidates[: CLOSE_POOL_MULT * KEEP_TOP]
    rescored = _rescore_joints(
        pool, rms, frame_rate, dur, track_mean, window_s, min_window_s,
        downbeats, beats_s,
    )
    rescored.sort(key=lambda c: c["final"], reverse=True)

    # Several grid anchors can snap to the same downbeat and pick the same
    # end, yielding identical clips with different open scores. Drop those
    # collisions (keep the best) before spreading, or the gap-halving
    # fallback below fills KEEP_TOP with duplicates.
    dedupe_gap = round(0.5 * frame_rate)
    deduped = []
    for c in rescored:
        if all(
            abs(c["off_frame"] - k["off_frame"]) >= dedupe_gap
            or abs(c["end_frame"] - k["end_frame"]) >= dedupe_gap
            for k in deduped
        ):
            deduped.append(c)

    min_gap_frames = round(max(dur / 10, 1.0) * frame_rate)
    kept = _suppress_neighbors(deduped, min_gap_frames, key="off_frame")

    return [
        {
            "offset_s": round(c["offset_s"], 2),
            "duration_s": round(c["end_s"] - c["offset_s"], 2),
            "end_s": round(c["end_s"], 2),
            "score": round(c["final"], 3),
            "reason": _reason(c),
            "d_close_beat_s": (
                round(c["d_close"], 3) if c["d_close"] is not None else None
            ),
            "close_closure": round(c["closure"], 3),
        }
        for c in kept
    ]


def _rescore_joints(
    pool: list[dict],
    rms: np.ndarray,
    frame_rate: float,
    dur: float,
    track_mean: float,
    window_s: float,
    min_window_s: float,
    downbeats: list[int],
    beats_s: list[float],
) -> list[dict]:
    """Joint-select (offset, end) per open-ranked candidate, per #3.5.

    Snaps each open to its downbeat, scores every beat-quantized end in
    `[offset + min_window_s, offset + window_s]` by closure, and keeps
    the best end. Closure is normalized by the pool maximum so the
    open/close blend compares within one track.

    Args:
        pool: Open-ranked candidate dicts with `start_frame` and
            normalized open `energy`/`flux`/`contrast` plus `score`.
        rms: Full-track RMS envelope at `frame_rate` frames per second.
        frame_rate: `SAMPLE_RATE / HOP_LENGTH`, in frames per second.
        dur: Track duration, in seconds.
        track_mean: Mean RMS over the track (closure loudness reference).
        window_s: Maximum window length, in seconds.
        min_window_s: Minimum window length, in seconds.
        downbeats: Downbeat frames the open snaps to.
        beats_s: All beat timestamps, in seconds, for end quantization.

    Returns:
        One dict per pool candidate: the open fields plus `offset_s`,
        `end_s`, `off_frame`/`end_frame` (ints, for dedupe/spreading),
        `d_close` (float | None, residual end-to-beat gap, nonzero only
        on the fixed-window fallback), `closure` (float, raw closure of
        the chosen end) and `final` (float, open/close blend, floored
        at 0).
    """
    rows: list[dict] = []
    for c in pool:
        anchor_s = c["start_frame"] / frame_rate + ANCHOR_SHIFT_S
        offset_s = max(0.0, _snap_to_downbeat(anchor_s, downbeats))
        ends = _candidate_ends(offset_s, dur, window_s, min_window_s, beats_s)
        rows.append({"open": c, "offset_s": offset_s, "ends": ends})
    raws = [
        raw
        for r in rows
        for e, _ in r["ends"]
        if (raw := _closure_raw(rms, frame_rate, e, track_mean)) > 0.0
    ]
    pool_max = max(raws, default=0.0)
    pool_max = pool_max if pool_max > 0 else 1e-6
    finalized = []
    for r in rows:
        scored = []
        for end_s, d_close in r["ends"]:
            raw = _closure_raw(rms, frame_rate, end_s, track_mean)
            beat_p = (
                0.0
                if d_close is None or d_close == 0.0
                else CLOSE_BEAT_PENALTY_W
                * min(d_close / CLOSE_BEAT_WINDOW_S, 1.0)
            )
            scored.append((raw / pool_max - beat_p, end_s, d_close, raw))
        scored.sort(key=lambda p: p[0], reverse=True)
        quality, end_s, d_close, raw = scored[0]
        finalized.append(
            {
                **r["open"],
                "offset_s": r["offset_s"],
                "end_s": end_s,
                "off_frame": round(r["offset_s"] * frame_rate),
                "end_frame": round(end_s * frame_rate),
                "d_close": d_close,
                "closure": raw,
                "final": max(
                    0.0, OPEN_MIX * r["open"]["score"] + END_MIX * quality
                ),
            }
        )
    return finalized


def _candidate_ends(
    offset_s: float,
    dur: float,
    window_s: float,
    min_window_s: float,
    beats_s: list[float],
) -> list[tuple[float, float | None]]:
    """List scorable `(end_s, d_close)` pairs for one snapped open.

    Ends are detected beats in `[offset + min_window_s, offset +
    window_s]` needing 0.5 s of post-boundary audio (`d_close = 0.0`).
    With no usable beat (sparse detection, or `min == max`), falls back
    to the single `offset + window_s` end nudged onto a beat where
    possible, carrying its residual gap as `d_close`.
    """
    ends: list[tuple[float, float | None]] = [
        (b, 0.0)
        for b in beats_s
        if offset_s + min_window_s <= b <= offset_s + window_s
        and b + 0.5 <= dur
    ]
    if ends:
        return ends
    _, end_s, d_close = _snap_end(offset_s, window_s, beats_s)
    return [(end_s, d_close)]


def _closure_raw(
    rms: np.ndarray, frame_rate: float, end_s: float, track_mean: float
) -> float:
    """Score one candidate end as a phrase closing point, per #3.5.

    Loud sustained energy in `CLOSE_PRE_S` before the boundary times the
    relative decay over `CLOSE_POST_S` after it: phrase endings score
    high, mid-sustain cutoffs ~0 (no decay), rising cutoffs 0 (negative
    decay clipped), quiet passages low (little pre-energy).

    Args:
        rms: Full-track RMS envelope at `frame_rate` frames per second.
        frame_rate: Frames per second of `rms`.
        end_s: Candidate boundary timestamp, in seconds.
        track_mean: Mean RMS over the track (loudness reference).

    Returns:
        Raw closure (coarse scale, normalized by the pool max in
        `_rescore_joints`); 0.0 when under 0.5 s of post-boundary audio
        exists to judge the decay (an unjudgeable end ranks bottom,
        like a decay-free one).
    """

    def mean(t0: float, t1: float) -> tuple[float, float]:
        n = len(rms)
        a = max(0, min(n, round(t0 * frame_rate)))
        b = max(a, min(n, round(t1 * frame_rate)))
        cov = max(0.0, min(t1, len(rms) / frame_rate) - max(t0, 0.0))
        return (float(np.mean(rms[a:b])) if b > a else 0.0, cov)

    pre, _ = mean(end_s - CLOSE_PRE_S, end_s)
    post, cov = mean(end_s, end_s + CLOSE_POST_S)
    if cov < 0.5:
        return 0.0
    eps = 1e-6
    decay = max(0.0, (pre - post) / (pre + eps))
    return (pre / (track_mean + eps)) * decay


def _normalize(candidates: list[dict], key: str) -> None:
    values = [c[key] for c in candidates]
    lo, hi = min(values), max(values)
    spread = hi - lo
    for c in candidates:
        c[key] = (c[key] - lo) / spread if spread > 0 else 0.0


def _suppress_neighbors(
    candidates: list[dict], min_gap_frames: int, key: str = "start_frame"
) -> list[dict]:
    """Keep up to `KEEP_TOP` ranked candidates, spread out where possible.

    Starts at `min_gap_frames` apart; if that leaves fewer than `KEEP_TOP`
    (short track, or peaks clustered together), halves the gap and retries
    so slots are still filled by real ranked candidates rather than falling
    back to blind evenly-spaced offsets.
    """
    gap = min_gap_frames
    kept: list[dict] = []
    while True:
        kept = []
        for c in candidates:
            if len(kept) >= KEEP_TOP:
                break
            if all(abs(c[key] - k[key]) >= gap for k in kept):
                kept.append(c)
        if len(kept) >= KEEP_TOP or gap == 0:
            return kept
        gap //= 2


def _reason(candidate: dict) -> str:
    dominant = max(("energy", "flux", "contrast"), key=lambda k: candidate[k])
    return {
        "energy": "sustained high energy",
        "flux": "dense onsets",
        "contrast": "energy jump (drop)",
    }[dominant]


def _snap_end(
    snapped_s: float, window_s: float, beats_s: list[float]
) -> tuple[float, float, float | None]:
    """Nudge a downbeat-snapped open so the window end lands on a beat.

    Shifts the start by at most `END_SNAP_MAX_S` (a small move that keeps
    the open effectively on the downbeat); larger gaps are left as-is and
    penalized in `_rescore_joints` instead. The nudge favors no direction: moving the
    start earlier keeps the downbeat transient, moving it later trims up to
    0.15 s of attack, which listening tests may want to revisit.

    Args:
        snapped_s: Downbeat-snapped start offset, in seconds.
        window_s: Highlight window length, in seconds.
        beats_s: All beat timestamps, in seconds.

    Returns:
        `(offset_s, end_s, d_close)`: the (possibly nudged, clamped at 0)
        start, `offset_s + window_s`, and the residual end-to-beat gap
        (`None` when `beats_s` is empty).
    """
    nearest = _nearest_beat(snapped_s + window_s, beats_s)
    if nearest is None:
        offset_s = max(0.0, snapped_s)
        return offset_s, offset_s + window_s, None
    if abs(nearest - (snapped_s + window_s)) <= END_SNAP_MAX_S:
        offset_s = max(0.0, snapped_s + (nearest - snapped_s - window_s))
        return offset_s, offset_s + window_s, 0.0
    offset_s = max(0.0, snapped_s)
    return offset_s, offset_s + window_s, abs(nearest - (offset_s + window_s))


def _nearest_beat(t: float, beats_s: list[float]) -> float | None:
    """Return the beat timestamp nearest to `t`, or `None` if no beats."""
    best: float | None = None
    for b in beats_s:
        if best is None or abs(b - t) < abs(best - t):
            best = b
    return best


def _beat_frames(y: np.ndarray, sr: float) -> list[int]:
    """Detect all beat frames (any beat: used for end quantization), per #3.5."""
    import librosa

    _, beat_frames = librosa.beat.beat_track(
        y=y, sr=sr, hop_length=HOP_LENGTH, units="frames"
    )
    return [int(b) for b in beat_frames]


def _downbeat_frames(
    beat_frames: list[int], onset_env: np.ndarray
) -> list[int]:
    """Pick the downbeat phase out of detected beats, assumed 4/4.

    Keeps the strongest of 4 beat phases by summed onset strength.

    ponytail: picks the strongest of 4 phases rather than tracking real
    downbeats; upgrade to madmom's downbeat tracker if a track isn't 4/4.

    Args:
        beat_frames: All detected beat frames (see `_beat_frames`).
        onset_env: Onset-strength envelope aligned to `beat_frames`.

    Returns:
        Every 4th beat frame starting at the strongest phase.
    """
    if len(beat_frames) < 4:
        return list(beat_frames)
    best_phase = max(
        range(4), key=lambda p: sum(onset_env[b] for b in beat_frames[p::4])
    )
    return list(beat_frames[best_phase::4])


def _snap_to_downbeat(offset_s: float, beat_frames: list[int]) -> float:
    if not beat_frames:
        return offset_s
    frame_rate = SAMPLE_RATE / HOP_LENGTH
    beats_s = [b / frame_rate for b in beat_frames]
    return min(beats_s, key=lambda b: abs(b - offset_s))
