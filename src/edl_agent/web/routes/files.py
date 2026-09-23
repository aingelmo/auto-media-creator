"""Serving session files (inputs, proxies, music) for library previews."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from edl_agent.paths import CACHE_DIR, SESSIONS_DIR

router = APIRouter()


@router.get("/sessions/{name}/reel.mp4")
def session_reel(name: str) -> FileResponse:
    """Serve the rendered reel for preview/download."""
    reel_path = SESSIONS_DIR / name / "reel.mp4"
    if not reel_path.exists():
        raise HTTPException(status_code=404)
    return FileResponse(reel_path, media_type="video/mp4")


@router.get("/sessions/{name}/files/{path:path}")
def session_file(name: str, path: str) -> FileResponse:
    """Serve a session-relative file for library previews.

    Args:
        name: Session directory name under `SESSIONS_DIR`.
        path: Session-relative path (e.g. `"inputs/clip.MOV"` or
            `"proxies/clip.mp4"`).

    Returns:
        The file contents with a guessed media type.

    Raises:
        HTTPException: 404 when the session/file is missing, the raw
            `path` tries to escape with `".."`, or the resolved file
            lands outside the app's runtime data (`SESSIONS_DIR` or
            `CACHE_DIR` — see `#3`). Resolving (not the raw path) is
            checked because library sessions reuse footage via symlinks:
            picked inputs link into another session's `inputs/`, and
            proxies link into the content-hash cache under `var/cache/`
            (`#3.3`). The previous session-dir-only check 404'd every
            such link, which is why library tiles rendered black.
    """
    if ".." in path.split("/"):
        raise HTTPException(status_code=404)
    session_dir = (SESSIONS_DIR / name).resolve()
    file_path = (session_dir / path).resolve()
    allowed = (SESSIONS_DIR.resolve(), CACHE_DIR.resolve())
    if not any(
        file_path == root or root in file_path.parents for root in allowed
    ):
        raise HTTPException(status_code=404)
    if not file_path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(file_path)
