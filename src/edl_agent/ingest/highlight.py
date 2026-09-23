"""Rank candidate 15s music windows by a drop-detection heuristic, per #3.5.

Scores every window start offset in a track on energy, onset flux, and
energy contrast (the jump that marks an EDM/trap drop), then snaps the
best offsets to the track's downbeat so a chosen clip opens on beat 1.
Because the window length is fixed, every downbeat-snapped open puts the
window end at the same beat phase, so ends are scored too: the start is
nudged (at most `END_SNAP_MAX_S`) to land the end on a beat, and any
remaining off-beat / rising-into-the-cut / weak ending deducts from the
score via `CLOSE_PENALTY`. Results are cached per-track
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

CACHE_VERSION = 2
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
# Close side: ends cut mid-phrase/off-beat when only the open is scored
# (fixed window + downbeat-snapped opens = constant end beat phase, so no
# open re-ranking alone can fix ends). Scores stay open-dominant: the close
# malus (0..1) deducts at most CLOSE_PENALTY from the open score.
CLOSE_PENALTY = 0.35
END_SNAP_MAX_S = 0.15  # max start shift applied to land the end on a beat
CLOSE_BEAT_WINDOW_S = 0.25  # end-to-beat gap at/above this is full beat malus
CLOSE_SLOPE_NORM = 0.5  # end energy slope at/above this is full slope malus
WEAK_CLOSE_RATIO = 0.6  # end-to-window energy ratio below this is a weak end
MALUS_BEAT_WEIGHT = 0.5
MALUS_SLOPE_WEIGHT = 0.3
MALUS_WEAK_WEIGHT = 0.2
CLOSE_POOL_MULT = 3  # close-rescore this multiple of KEEP_TOP open-ranked


def rank_highlights(
    track: Path, window_s: float, *, cache_root: Path | None = None
) -> list[dict]:
    """Rank candidate `window_s` start offsets in `track`, best first.

    Args:
        track: Path to the music file.
        window_s: Length of the highlight window to rank offsets for, in
            seconds.
        cache_root: If given, cache the ranking under
            `cache_root/<sha256 of track>/music_highlights.json` and reuse
            it on a later call with the same `track`/`window_s`.

    Returns:
        Ranked list of dicts (best first), each with `offset_s` (float,
        snapped to the downbeat and nudged by at most `END_SNAP_MAX_S`
        so the window end lands on a beat), `end_s` (float,
        `offset_s + window_s`), `score` (float, 0..1, open score minus
        the close malus), `reason` (str, dominant open component),
        `d_close_beat_s` (float | None, residual end-to-beat gap after
        the nudge; `None` when no beats were detected) and
        `close_malus` (float, 0..1).
    """
    cache_path = None
    if cache_root is not None:
        cache_path = source_cache_dir(cache_root, sha256_file(track)) / (
            "music_highlights.json"
        )
        cached = _read_cache(cache_path, window_s)
        if cached is not None:
            return cached

    ranked = _rank(track, window_s)

    if cache_path is not None:
        atomic_write_text(
            cache_path,
            json.dumps(
                {"version": CACHE_VERSION, "window_s": window_s, "ranked": ranked}
            ),
        )
    return ranked


def _read_cache(cache_path: Path, window_s: float) -> list[dict] | None:
    if not cache_path.exists():
        return None
    data = json.loads(cache_path.read_text())
    if data.get("version") != CACHE_VERSION or data.get("window_s") != window_s:
        return None
    return data["ranked"]


def _rank(track: Path, window_s: float) -> list[dict]:
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

    pool = candidates[: CLOSE_POOL_MULT * KEEP_TOP]
    rescored = [
        _score_close(c, rms, frame_rate, window_s, downbeats, beats_s)
        for c in pool
    ]
    rescored.sort(key=lambda c: c["final"], reverse=True)

    min_gap_frames = round(max(dur / 10, 1.0) * frame_rate)
    kept = _suppress_neighbors(rescored, min_gap_frames, key="off_frame")

    return [
        {
            "offset_s": round(c["offset_s"], 2),
            "end_s": round(c["end_s"], 2),
            "score": round(c["final"], 3),
            "reason": _reason(c),
            "d_close_beat_s": (
                round(c["d_close"], 3) if c["d_close"] is not None else None
            ),
            "close_malus": round(c["malus"], 3),
        }
        for c in kept
    ]


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


def _score_close(
    open_cand: dict,
    rms: np.ndarray,
    frame_rate: float,
    window_s: float,
    downbeats: list[int],
    beats_s: list[float],
) -> dict:
    """Snap one open-ranked candidate and deduct the ending malus, per #3.5.

    Args:
        open_cand: Candidate dict with `start_frame` and normalized open
            `energy`/`flux`/`contrast` plus `score` (the open score).
        rms: Full-track RMS envelope at `frame_rate` frames per second.
        frame_rate: `SAMPLE_RATE / HOP_LENGTH`, in frames per second.
        window_s: Highlight window length, in seconds.
        downbeats: Downbeat frames the open snaps to (see
            `_downbeat_frames`).
        beats_s: All beat timestamps, in seconds, for end-snapping.

    Returns:
        `open_cand` plus `offset_s`/`end_s` (floats, seconds),
        `off_frame` (int, `offset_s` in frames, for neighbor
        suppression), `d_close` (float | None, residual end-to-beat gap),
        `malus` (float, 0..1) and `final` (float, open score minus
        `CLOSE_PENALTY * malus`, floored at 0).
    """
    anchor_s = open_cand["start_frame"] / frame_rate + ANCHOR_SHIFT_S
    snapped = _snap_to_downbeat(anchor_s, downbeats)
    offset_s, end_s, d_close = _snap_end(snapped, window_s, beats_s)
    _win_mean, close_ratio, end_slope = _close_features(
        rms, frame_rate, offset_s, window_s
    )
    beat_m = 0.0 if d_close is None else min(d_close / CLOSE_BEAT_WINDOW_S, 1.0)
    slope_m = min(max(end_slope, 0.0) / CLOSE_SLOPE_NORM, 1.0)
    weak_m = min(
        max(WEAK_CLOSE_RATIO - close_ratio, 0.0) / WEAK_CLOSE_RATIO, 1.0
    )
    malus = (
        MALUS_BEAT_WEIGHT * beat_m
        + MALUS_SLOPE_WEIGHT * slope_m
        + MALUS_WEAK_WEIGHT * weak_m
    )
    return {
        **open_cand,
        "offset_s": offset_s,
        "end_s": end_s,
        "off_frame": round(offset_s * frame_rate),
        "d_close": d_close,
        "malus": malus,
        "final": max(0.0, open_cand["score"] - CLOSE_PENALTY * malus),
    }


def _snap_end(
    snapped_s: float, window_s: float, beats_s: list[float]
) -> tuple[float, float, float | None]:
    """Nudge a downbeat-snapped open so the window end lands on a beat.

    Shifts the start by at most `END_SNAP_MAX_S` (a small move that keeps
    the open effectively on the downbeat); larger gaps are left as-is and
    surface as malus instead. The nudge favors no direction: moving the
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


def _close_features(
    rms: np.ndarray, frame_rate: float, offset_s: float, window_s: float
) -> tuple[float, float, float]:
    """Describe how a window ends from its RMS envelope, per #3.5.

    Args:
        rms: Full-track RMS envelope at `frame_rate` frames per second.
        frame_rate: Frames per second of `rms`.
        offset_s: Window start offset, in seconds.
        window_s: Window length, in seconds.

    Returns:
        `(win_mean, close_ratio, end_slope)`: mean RMS over the window,
        mean RMS over the last 0.5 s relative to the window mean (below
        `WEAK_CLOSE_RATIO` is a weak ending), and the last-0.5 s mean
        minus the preceding 1 s mean, relative to the window mean
        (positive values are still climbing into the cut: abrupt).
    """

    def mean(t0: float, t1: float) -> float:
        n = len(rms)
        a = max(0, min(n, round(t0 * frame_rate)))
        b = max(a + 1, min(n, round(t1 * frame_rate)))
        return float(np.mean(rms[a:b]))

    end_s = offset_s + window_s
    win_mean = mean(offset_s, end_s)
    close_mean = mean(end_s - 0.5, end_s)
    pre_mean = mean(end_s - 1.5, end_s - 0.5)
    eps = 1e-6
    return win_mean, close_mean / (win_mean + eps), (close_mean - pre_mean) / (
        win_mean + eps
    )


def _beat_frames(y: np.ndarray, sr: float) -> list[int]:
    """Detect all beat frames (any beat: used for end-snapping), per #3.5."""
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
