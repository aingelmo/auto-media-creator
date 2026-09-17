"""Lists previously-used clips/music across sessions, for the new-session picker."""

from __future__ import annotations

from fastapi import APIRouter

from edl_agent.paths import SESSIONS_DIR
from edl_agent.session._common import IMAGE_EXTS, MUSIC_EXTS, VIDEO_EXTS

router = APIRouter()


def _scan(subdir: str, exts: set[str]) -> list[dict]:
    """Session-relative files under `{session}/{subdir}/`, newest first.

    Deduped by `(filename, size)` — a lazy stand-in for content hashing,
    good enough since a re-upload of the same file keeps the same name/size.
    """
    if not SESSIONS_DIR.is_dir():
        return []
    entries = []
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
    deduped = []
    for e in entries:
        key = (e["filename"], e["size"])
        if key in seen:
            continue
        seen.add(key)
        del e["mtime"]
        deduped.append(e)
    return deduped


@router.get("/api/media")
def list_media() -> dict:
    """Clips/music already on disk from past sessions, for the picker in `New.tsx`."""
    return {
        "clips": _scan("inputs", VIDEO_EXTS | IMAGE_EXTS),
        "music": _scan("music", MUSIC_EXTS),
    }
