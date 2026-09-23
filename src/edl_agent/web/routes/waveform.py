"""Waveform peaks for library tracks, served lazily per track.

The dashboard and picker render one waveform per visible track, so
computing envelopes for the whole library up front would stall the first
paint. This router exposes one endpoint per track instead; results are
cached in `var/cache/media_peaks.json` keyed by absolute path, size, and
mtime, the same scheme `routes/media.py` uses for probe metadata.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from edl_agent.ingest.waveform import PEAK_BUCKETS, extract_peaks, measure_loudness
from edl_agent.paths import CACHE_DIR, SESSIONS_DIR

router = APIRouter()

# Subdirectory of a session that holds original music uploads; peaks are
# only served for files here (never generated output like track_cut.wav).
MUSIC_SUBDIR = "music"

_PEAKS_CACHE_PATH = CACHE_DIR / "media_peaks.json"


def _load_cache() -> dict[str, Any]:
    """Read the on-disk peaks cache, or `{}` on any failure.

    Returns:
        Mapping of `"{abspath}:{size}:{mtime}"` to `list[float]` peaks.
        Corrupt or missing caches degrade to an empty mapping so a bad
        cache file never breaks the waveform endpoint.
    """
    try:
        return json.loads(_PEAKS_CACHE_PATH.read_text())
    except (OSError, ValueError):
        return {}


def _save_cache(cache: dict[str, Any]) -> None:
    """Persist the peaks cache, best-effort.

    Args:
        cache: Mapping of cache key to peaks list. Write failures are
            swallowed: peaks are an optimisation and listing must work
            when `var/` is read-only.
    """
    try:
        _PEAKS_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _PEAKS_CACHE_PATH.write_text(json.dumps(cache))
    except OSError:
        pass


def _resolve_ref(ref: str) -> Path:
    """Resolve a `"{session}/{subdir}/{filename}"` ref to a file on disk.

    Args:
        ref: Session-relative media reference as produced by
            `GET /api/media` (`entry["session"] + "/" + entry["path"]`).

    Returns:
        Absolute path to the referenced music file.

    Raises:
        HTTPException: 404 if the ref is absolute or contains `..`, if it
            is not a file under `{sessions}/{session}/music/`, or if the
            resolved path escapes the sessions root.
    """
    parts = Path(ref).parts
    if Path(ref).is_absolute() or ".." in parts or len(parts) != 3:
        raise HTTPException(status_code=404, detail="unknown media ref")
    if parts[1] != MUSIC_SUBDIR:
        raise HTTPException(status_code=404, detail="peaks are music-only")
    candidate = (SESSIONS_DIR / ref).resolve()
    try:
        candidate.relative_to(SESSIONS_DIR.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="unknown media ref") from exc
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="unknown media ref")
    return candidate


@router.get("/api/media/peaks")
def media_peaks(
    ref: str, buckets: int = PEAK_BUCKETS, start_s: float | None = None,
    end_s: float | None = None,
) -> dict:
    """Amplitude envelope for one library track, computed on first request.

    Args:
        ref: Session-relative music reference, `"{session}/music/{file}"`,
            as returned in `/api/media`'s `music` entries.
        buckets: Number of peak buckets to return (clamped to 32..1024).
            Zoomed windows request the same count over a shorter range
            so bars stay crisp instead of stretching the full-track
            envelope.
        start_s: Optional range start in seconds for zoomed windows.
        end_s: Optional range end in seconds (exclusive). Both must be
            given (and `end_s > start_s`) to enable ranged decode;
            otherwise the full track is returned.

    Returns:
        Dict with `peaks`: a list of `0.0`-`1.0` floats (see
        `edl_agent.ingest.waveform.extract_peaks`), plus `start_s` /
        `end_s` echoing the requested range (`None` for full track).
        Tracks ffmpeg cannot decode return an empty list rather than
        an error, so one bad file leaves the surrounding list intact.

    Raises:
        HTTPException: 404 when `ref` does not name a music file inside a
            session (see `_resolve_ref`).
    """
    path = _resolve_ref(ref)
    stat = path.stat()
    n = max(32, min(1024, int(buckets or PEAK_BUCKETS)))
    s: float | None = None
    w: float | None = None
    e: float | None = None
    if start_s is not None and end_s is not None:  # noqa: SIM102
        if start_s >= 0 and end_s > start_s:
            s = float(start_s)
            w = float(end_s - start_s)
            e = float(end_s)
    key = f"{path}:{stat.st_size}:{stat.st_mtime}:{n}:{s}:{w}"
    cache = _load_cache()
    peaks = cache.get(key)
    if peaks is None:
        try:
            peaks = extract_peaks(path, buckets=n, start_s=s, window_s=w)
        except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
            peaks = []
        cache[key] = peaks
        _save_cache(cache)
    return {"peaks": peaks, "start_s": s, "end_s": e}


_LOUD_CACHE_PATH = CACHE_DIR / "media_loudness.json"


def _load_loud_cache() -> dict[str, Any]:
    """Read the on-disk loudness cache, or `{}` on any failure.

    Returns:
        Mapping of `"{abspath}:{size}:{mtime}"` to loudness dict. Corrupt
        or missing caches degrade to empty so a bad file never breaks
        the endpoint.
    """
    try:
        return json.loads(_LOUD_CACHE_PATH.read_text())
    except (OSError, ValueError):
        return {}


def _save_loud_cache(cache: dict[str, Any]) -> None:
    """Persist the loudness cache, best-effort.

    Args:
        cache: Mapping of cache key to loudness dict. Write failures are
            swallowed: loudness is an optimisation.
    """
    try:
        _LOUD_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _LOUD_CACHE_PATH.write_text(json.dumps(cache))
    except OSError:
        pass


@router.get("/api/media/loudness")
def media_loudness(ref: str) -> dict:
    """Loudness summary for one library track, cached per file.

    Args:
        ref: Session-relative music reference, `"{session}/music/{file}"`.

    Returns:
        Dict with `mean_volume_db`, `max_volume_db` (`float` or `None`
        for silence/unmeasurable), and `peak` (`0.0`-`1.0` linear).

    Raises:
        HTTPException: 404 when `ref` does not name a music file inside a
            session (see `_resolve_ref`).
    """
    path = _resolve_ref(ref)
    stat = path.stat()
    key = f"{path}:{stat.st_size}:{stat.st_mtime}"
    cache = _load_loud_cache()
    loud = cache.get(key)
    if loud is None:
        loud = measure_loudness(path)
        cache[key] = loud
        _save_loud_cache(cache)
    return loud
