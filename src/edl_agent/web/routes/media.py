"""Lists previously-used clips/music across sessions, for the new-session picker."""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter

from edl_agent.ingest.probe import ffprobe, post_rotation_dims
from edl_agent.paths import CACHE_DIR, SESSIONS_DIR
from edl_agent.session._common import IMAGE_EXTS, MUSIC_EXTS, VIDEO_EXTS

if TYPE_CHECKING:
    from pathlib import Path

router = APIRouter()

# Newest-first cap on probed entries per list, per the intake redesign:
# keeps `/api/media` fast and the picker DOM light for phone-dump users.
MEDIA_SCAN_LIMIT = 200

_META_CACHE_PATH = CACHE_DIR / "media_meta.json"


def _load_meta_cache() -> dict[str, dict[str, Any]]:
    """Read the on-disk ffprobe metadata cache, or empty on any failure.

    Returns:
        Mapping of cache key to probed metadata dict. Corrupt/missing
        cache files yield `{}` rather than raising, so listing never
        fails because of a stale cache.
    """
    try:
        return json.loads(_META_CACHE_PATH.read_text())
    except (OSError, ValueError):
        return {}


def _save_meta_cache(cache: dict[str, dict[str, Any]]) -> None:
    """Persist the ffprobe metadata cache, best-effort.

    Args:
        cache: Mapping of cache key to probed metadata dict. Write
            failures are swallowed: caching is an optimisation, and
            listing must work even when `var/` is read-only.
    """
    try:
        _META_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _META_CACHE_PATH.write_text(json.dumps(cache))
    except OSError:
        pass


def _format_duration_s(probe: dict[str, Any]) -> float | None:
    """Pull total duration seconds out of an ffprobe result, leniently.

    Args:
        probe: Parsed ffprobe JSON with `format` and `streams` keys.

    Returns:
        Duration in seconds, or `None` when absent/unparseable (e.g.
        still images, which carry no duration).
    """
    try:
        return float(probe["format"]["duration"])
    except (KeyError, TypeError, ValueError):
        return None


def _probe_file(path: Path, audio_only: bool = False) -> dict[str, Any]:
    """Probe one media file for picker metadata, never raising.

    Args:
        path: Absolute path to the media file on disk.
        audio_only: When `True` (music-library scan), report `kind`
            `"audio"` even if the container holds a video stream (music
            `.mp4`/`.m4a` files), and skip width/height.

    Returns:
        Dict with `duration_s` (`float` or `None`), `w`/`h` (`int` or
        `None`, post-rotation), and `kind` (`"video"`, `"image"`, or
        `"audio"`). Any ffprobe failure yields `None` dimensions rather
        than raising, so one corrupt file can't break the listing.
    """
    suffix = path.suffix.lower()
    fallback_kind = (
        "audio" if audio_only else ("image" if suffix in IMAGE_EXTS else "video")
    )
    try:
        probe = ffprobe(path)
        streams = probe.get("streams", [])
        video = next((s for s in streams if s.get("codec_type") == "video"), None)
        if audio_only or video is None:
            return {
                "duration_s": _format_duration_s(probe),
                "w": None,
                "h": None,
                "kind": "audio",
            }
        raw_w, raw_h = int(video["width"]), int(video["height"])
        rotation = 0
        for sd in video.get("side_data_list", []):
            if "rotation" in sd:
                rotation = int(sd["rotation"])
                break
        else:
            tag = video.get("tags", {}).get("rotate")
            rotation = int(tag) if tag else 0
        w, h = post_rotation_dims(raw_w, raw_h, rotation)
        duration_s: float | None
        try:
            duration_s = float(video.get("duration") or probe["format"]["duration"])
        except (KeyError, TypeError, ValueError):
            duration_s = None
        kind = "image" if suffix in IMAGE_EXTS else "video"
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        subprocess.CalledProcessError,
    ):
        return {"duration_s": None, "w": None, "h": None, "kind": fallback_kind}
    else:
        return {"duration_s": duration_s, "w": w, "h": h, "kind": kind}


def _scan(subdir: str, exts: set[str]) -> list[dict]:
    """Session-relative files under `{session}/{subdir}/`, newest first.

    Deduped by `(filename, size)` — a lazy stand-in for content hashing,
    good enough since a re-upload of the same file keeps the same name/size.
    Capped at `MEDIA_SCAN_LIMIT` entries, each enriched with ffprobe
    metadata (`duration_s`, `w`, `h`, `kind`) served from a disk cache in
    `var/cache/media_meta.json` keyed by absolute path, size, and mtime.
    """
    if not SESSIONS_DIR.is_dir():
        return []
    entries: list[dict[str, Any]] = []
    for session_dir in SESSIONS_DIR.iterdir():
        d = session_dir / subdir
        if not d.is_dir():
            continue
        for f in d.iterdir():
            if not f.is_file() or f.suffix.lower() not in exts:
                continue
            if subdir == "music" and f.name == "track_cut.wav":
                continue  # generated output, not an original upload
            stat = f.stat()
            entries.append(
                {
                    "session": session_dir.name,
                    "path": f"{subdir}/{f.name}",
                    "filename": f.name,
                    "size": stat.st_size,
                    "mtime": stat.st_mtime,
                }
            )
    entries.sort(key=lambda e: e["mtime"], reverse=True)
    seen: set[tuple[str, int]] = set()
    deduped: list[dict[str, Any]] = []
    for e in entries:
        key = (str(e["filename"]), int(e["size"]))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(e)
        if len(deduped) >= MEDIA_SCAN_LIMIT:
            break
    cache = _load_meta_cache()
    dirty = False
    audio_only = subdir == "music"
    for e in deduped:
        abspath = (SESSIONS_DIR / e["session"] / e["path"]).resolve()
        cache_key = f"{abspath}:{e['size']}:{e['mtime']}"
        meta = cache.get(cache_key)
        if meta is None:
            meta = _probe_file(abspath, audio_only=audio_only)
            cache[cache_key] = meta
            dirty = True
        e.update(meta)
        del e["mtime"]
    if dirty:
        _save_meta_cache(cache)
    return deduped


@router.get("/api/media")
def list_media() -> dict:
    """Clips/music already on disk from past sessions, for the picker in `New.tsx`.

    Returns:
        Dict with `clips` (from each session's `inputs/`) and `music`
        (from `music/`), each entry carrying `session`, `path`,
        `filename`, `size`, plus probed `duration_s`, `w`, `h`, `kind`.
        Both lists are newest-first and capped at `MEDIA_SCAN_LIMIT`.
    """
    return {
        "clips": _scan("inputs", VIDEO_EXTS | IMAGE_EXTS),
        "music": _scan("music", MUSIC_EXTS),
    }
