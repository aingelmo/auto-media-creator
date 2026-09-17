"""Serving the rendered reel and raw session files for the debug views."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from edl_agent.paths import SESSIONS_DIR

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
    """Serve a session-relative file for debug views."""
    session_dir = (SESSIONS_DIR / name).resolve()
    file_path = (session_dir / path).resolve()
    if session_dir not in file_path.parents or not file_path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(file_path)
