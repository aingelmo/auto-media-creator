"""Rank candidate 15s music windows by a drop-detection heuristic, per #3.5.

Scores every window start offset in a track on energy, onset flux, and
energy contrast (the jump that marks an EDM/trap drop), then snaps the
best offsets to the track's downbeat so a chosen clip opens on beat 1.
Results are cached per-track (content-addressed, alongside proxy/feature
caches) since sessions reuse the same music across runs.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np

from edl_agent.ingest._common import sha256_file
from edl_agent.ingest.cache import atomic_write_text, source_cache_dir
from edl_agent.ingest.media import cut_music

CACHE_VERSION = 1
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
        Ranked list of dicts (best first), each with `offset_s` (float),
        `score` (float, 0..1) and `reason` (str).
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

    min_gap_frames = round(max(dur / 10, 1.0) * frame_rate)
    kept = _suppress_neighbors(candidates, min_gap_frames)

    beat_frames = _downbeat_frames(y, sr, onset_env)
    results = []
    for c in kept:
        anchor_s = c["start_frame"] / frame_rate + ANCHOR_SHIFT_S
        offset_s = _snap_to_downbeat(anchor_s, beat_frames)
        results.append(
            {
                "offset_s": round(offset_s, 2),
                "score": round(c["score"], 3),
                "reason": _reason(c),
            }
        )
    return results


def _normalize(candidates: list[dict], key: str) -> None:
    values = [c[key] for c in candidates]
    lo, hi = min(values), max(values)
    spread = hi - lo
    for c in candidates:
        c[key] = (c[key] - lo) / spread if spread > 0 else 0.0


def _suppress_neighbors(candidates: list[dict], min_gap_frames: int) -> list[dict]:
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
            if all(abs(c["start_frame"] - k["start_frame"]) >= gap for k in kept):
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


def _downbeat_frames(y: np.ndarray, sr: float, onset_env: np.ndarray) -> list[int]:
    """Beat frames assumed 4/4, phase-picked by summed onset strength.

    ponytail: picks the strongest of 4 phases rather than tracking real
    downbeats; upgrade to madmom's downbeat tracker if a track isn't 4/4.
    """
    import librosa

    _, beat_frames = librosa.beat.beat_track(
        y=y, sr=sr, hop_length=HOP_LENGTH, units="frames"
    )
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
