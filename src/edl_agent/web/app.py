"""FastAPI app: local, no-auth JSON API + SPA static host for edl-agent.

Run with `uv run scripts/run_web.py`. See `edl_agent.web.pipeline` for the
job-orchestration logic and `edl_agent.web.routes` for the per-resource
routers this app mounts. The browser UI is a React SPA built into
`web/static/` (see `frontend/`); this module serves its JSON API under
`/api/*` plus the built assets and raw session files.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from edl_agent.startup import ensure_runtime_dirs, ensure_vendor_cache_env
from edl_agent.web.routes import (
    config,
    files,
    media,
    sessions,
    settings,
    stages,
    studio,
    trash,
    uploads,
    waveform,
)

STATIC_DIR = Path(__file__).parent / "static"


if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Pin vendor caches and verify the data volume before serving."""
    ensure_vendor_cache_env()
    ensure_runtime_dirs()
    yield


app = FastAPI(title="edl-agent", lifespan=lifespan)
app.include_router(sessions.router)
app.include_router(files.router)
app.include_router(stages.router)
app.include_router(studio.router)
app.include_router(config.router)
app.include_router(settings.router)
app.include_router(media.router)
app.include_router(trash.router)
app.include_router(waveform.router)
app.include_router(uploads.router)


@app.get("/health", include_in_schema=False)
def health() -> dict[str, str]:
    """Liveness probe for container orchestrators and reverse proxies.

    Must stay dependency-free (no ffmpeg/LLM/filesystem checks) so it
    answers 200 within the homelab probe's start window even while a
    pipeline job is running. Defined before the SPA catch-all below so
    the `/{full_path:path}` route can't shadow it.

    Returns:
        Dict with a single `status` key set to `"ok"`.
    """
    return {"status": "ok"}

# Mounted at /assets (not "/") so it can't shadow the /api and /sessions
# routes above; the catch-all route below serves index.html for every other
# GET so the SPA's client-side router (react-router) handles deep links.
if STATIC_DIR.is_dir():
    _assets_dir = str(STATIC_DIR / "assets")
    app.mount("/assets", StaticFiles(directory=_assets_dir), name="assets")

    _index_html = STATIC_DIR / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str) -> FileResponse:  # noqa: ARG001
        """Serve the built SPA shell for any GET not matched above."""
        return FileResponse(_index_html)
