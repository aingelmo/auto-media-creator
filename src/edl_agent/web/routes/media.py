"""Lists previously-used clips/music across sessions, for the new-session picker."""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Query

from edl_agent.ingest.probe import ffprobe, post_rotation_dims
from edl_agent.paths import CACHE_DIR, SESSIONS_DIR
from edl_agent.session._common import IMAGE_EXTS, MUSIC_EXTS, VIDEO_EXTS
from edl_agent.web import trash
from edl_agent.web.artifacts import clear_stage_artifacts
from edl_agent.web.state import jobs

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
    The `mtime` (unix seconds) is kept in the output so callers can show
    recency without an extra stat call.
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
    if dirty:
        _save_meta_cache(cache)
    return deduped


@router.get("/api/media")
def list_media() -> dict:
    """Clips/music already on disk from past sessions, for the picker in `New.tsx`.

    Returns:
        Dict with `clips` (from each session's `inputs/`) and `music`
        (from `music/`), each entry carrying `session`, `path`,
        `filename`, `size`, `mtime` (unix seconds, newest-first), plus
        probed `duration_s`, `w`, `h`, `kind`.
        Both lists are newest-first and capped at `MEDIA_SCAN_LIMIT`.
    """
    return {
        "clips": _scan("inputs", VIDEO_EXTS | IMAGE_EXTS),
        "music": _scan("music", MUSIC_EXTS),
    }


def _parse_media_ref(ref: str) -> tuple[str, str]:
    """Split a `"{session}/{path}"` library ref into its parts.

    Args:
        ref: Library ref as returned by `list_media` entries
            (`session` + session-relative `path`).

    Returns:
        `(session, relpath)` tuple.

    Raises:
        HTTPException: 400 if the ref is malformed or points at a
            generated file (`track_cut.wav`) or an unsupported
            directory/extension; 404 if the session or file is missing.
    """
    session, _, relpath = ref.partition("/")
    if not session or not relpath or ".." in relpath.split("/"):
        raise HTTPException(status_code=400, detail=f"malformed media ref {ref!r}")
    subdir, _, filename = relpath.partition("/")
    if subdir not in ("inputs", "music") or not filename or "/" in filename:
        raise HTTPException(status_code=400, detail=f"malformed media ref {ref!r}")
    if filename == "track_cut.wav":
        raise HTTPException(
            status_code=400, detail="track_cut.wav is generated output, not deletable"
        )
    ext = f".{filename.rsplit('.', 1)[-1].lower()}" if "." in filename else ""
    allowed = (VIDEO_EXTS | IMAGE_EXTS) if subdir == "inputs" else MUSIC_EXTS
    if ext not in allowed:
        raise HTTPException(status_code=400, detail=f"unsupported file type {ref!r}")
    session_dir = SESSIONS_DIR / session
    if not session_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"no such session {session!r}")
    target = session_dir / relpath
    if not target.is_symlink() and not target.is_file():
        raise HTTPException(status_code=404, detail=f"no such media {ref!r}")
    return session, relpath


def _evict_meta_cache(abspath_str: str) -> None:
    """Drop ffprobe cache rows for one absolute file path, best-effort.

    Args:
        abspath_str: Resolved absolute path whose `"{path}:*"` cache keys
            should go. Cache write failures are swallowed (see
            `_save_meta_cache`).
    """
    cache = _load_meta_cache()
    doomed = [k for k in cache if k.startswith(f"{abspath_str}:")]
    if not doomed:
        return
    for k in doomed:
        del cache[k]
    _save_meta_cache(cache)


def _pop_manifest_entry(
    session: str, relpath: str
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Drop one source/music entry from a session's `manifest.json`, if present.

    Args:
        session: Session directory name under `SESSIONS_DIR`.
        relpath: Session-relative path (e.g. `"inputs/clip.mp4"`) to drop
            from `sources` (or from `music` when it matches `music.src`).
            A missing `manifest.json` is a no-op; the file is rewritten
            only when an entry was actually removed.

    Returns:
        `(source_entry, music_entry)` — the removed `sources` entry and the
        removed `music` entry, each `None` when it was not present. The
        caller keeps them in the trash record so a restore can re-insert
        them verbatim.
    """
    manifest_path = SESSIONS_DIR / session / "manifest.json"
    if not manifest_path.is_file():
        return None, None
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, ValueError):
        return None, None
    sources = manifest.get("sources", [])
    removed_source = next((s for s in sources if s.get("src") == relpath), None)
    music = manifest.get("music")
    removed_music = (
        music if isinstance(music, dict) and music.get("src") == relpath else None
    )
    if removed_source is None and removed_music is None:
        return None, None
    manifest["sources"] = [s for s in sources if s.get("src") != relpath]
    if removed_music is not None:
        manifest.pop("music", None)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    return removed_source, removed_music


def restore_media_manifest(item: dict[str, Any]) -> None:
    """Re-insert a restored media item's entries into its session manifest.

    Backs `POST /api/trash/{id}/restore` for kind `"media"`: the trash
    record captured the `sources`/`music` entries at delete time, so a
    restore puts the session back the way it was. Derived stage artifacts
    stay cleared and rebuild on the next run.

    Args:
        item: A media trash record from `web.trash.restore_item`, carrying
            `session`, `source_entry`, and `music_entry`.
    """
    manifest_path = SESSIONS_DIR / str(item.get("session", "")) / "manifest.json"
    if not manifest_path.is_file():
        return
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, ValueError):
        return
    sources = manifest.setdefault("sources", [])
    source_entry = item.get("source_entry")
    if isinstance(source_entry, dict) and not any(
        s.get("src") == source_entry.get("src") for s in sources
    ):
        sources.append(source_entry)
    music_entry = item.get("music_entry")
    if isinstance(music_entry, dict):
        manifest["music"] = music_entry
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))


@router.delete("/api/media")
def delete_media(ref: str = Query(...)) -> dict:
    """Move one library file (that session copy only) to the trash.

    Moves the file without following symlinks, so a picked ref only drops
    the link in its own session while the shared original stays put.
    Removes the matching derived output (`proxies/<stem>.mp4` /
    `inputs_norm/<stem>.jpg` for clips, `music/track_cut.wav` for tracks),
    drops the entry from `manifest.json` (keeping it in the trash record
    for restore), and clears `candidates`-onward artifacts so the next run
    rebuilds cleanly. The payload stays restorable from `var/trash` for the
    retention window.

    Args:
        ref: `"{session}/{path}"` library ref from `list_media`.

    Returns:
        Dict with the trashed `ref` and the trash `item` record.

    Raises:
        HTTPException: 400 for a malformed ref, a generated/unsupported
            file, or deleting the session's last clip/music track; 404 for
            a missing session/file; 409 while the owning session has a live
            (not `done`) job.
    """
    session, relpath = _parse_media_ref(ref)
    job = jobs.get(session)
    if job is not None and not job.done:
        raise HTTPException(
            status_code=409, detail=f"session {session!r} has a running job"
        )
    session_dir = SESSIONS_DIR / session
    subdir = relpath.split("/", 1)[0]
    target = session_dir / relpath
    if subdir == "inputs":
        allowed = VIDEO_EXTS | IMAGE_EXTS
        siblings = [
            f
            for f in (session_dir / "inputs").iterdir()
            if (f.is_file() or f.is_symlink()) and f.suffix.lower() in allowed
        ]
        remaining = [f for f in siblings if f.name != target.name]
        if not remaining:
            raise HTTPException(
                status_code=400, detail="cannot delete the session's last clip"
            )
    else:
        siblings = [
            f
            for f in (session_dir / "music").iterdir()
            if (f.is_file() or f.is_symlink())
            and f.suffix.lower() in MUSIC_EXTS
            and f.name != "track_cut.wav"
        ]
        remaining = [f for f in siblings if f.name != target.name]
        if not remaining:
            raise HTTPException(
                status_code=400, detail="cannot delete the session's only track"
            )
    try:
        abspath_str = str(target.resolve())
    except OSError:
        abspath_str = str(target.absolute())
    stem = target.stem
    if subdir == "inputs":
        (session_dir / "proxies" / f"{stem}.mp4").unlink(missing_ok=True)
        (session_dir / "inputs_norm" / f"{stem}.jpg").unlink(missing_ok=True)
    else:
        (session_dir / "music" / "track_cut.wav").unlink(missing_ok=True)
    source_entry, music_entry = _pop_manifest_entry(session, relpath)
    clear_stage_artifacts(session_dir, "candidates")
    _evict_meta_cache(abspath_str)
    item = trash.trash_media(
        session,
        relpath,
        source_entry=source_entry,
        music_entry=music_entry,
    )
    return {"ref": ref, "item": item}
