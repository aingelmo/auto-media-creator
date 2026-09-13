"""FastAPI app: local, no-auth UI for running edl-agent sessions.

Run with `uv run scripts/run_web.py`. Job progress is tracked in an
in-memory dict, so it does not survive a server restart -- fine for a
local, single-process, single-user tool (see `web/pipeline.py`).
"""

from __future__ import annotations

import shutil
import threading
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from edl_agent.llm import PROVIDERS
from edl_agent.session._common import IMAGE_EXTS, VIDEO_EXTS
from edl_agent.web.pipeline import DEFAULT_MODELS, JobState, run_pipeline_job

SESSIONS_DIR = Path("sessions")
TEMPLATES_DIR = Path(__file__).parent / "templates"

app = FastAPI(title="edl-agent")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# session name -> JobState, for runs started by this process.
_jobs: dict[str, JobState] = {}
_lock = threading.Lock()


def _session_status(name: str) -> str:
    """Derive a session's display status for the home page listing.

    Args:
        name: Session directory name under `SESSIONS_DIR`.

    Returns:
        `"failed"`/`"running"` if tracked in `_jobs`, `"done"` if
        `reel.mp4` already exists on disk, `"new"` otherwise.
    """
    job = _jobs.get(name)
    if job is not None:
        if job.error:
            return "failed"
        if not job.done:
            return "running"
    if (SESSIONS_DIR / name / "reel.mp4").exists():
        return "done"
    return "new"


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    """List existing sessions with their derived status."""
    dirs = SESSIONS_DIR.iterdir() if SESSIONS_DIR.exists() else []
    names = sorted(p.name for p in dirs if p.is_dir())
    sessions = [{"name": n, "status": _session_status(n)} for n in names]
    return templates.TemplateResponse(request, "index.html", {"sessions": sessions})


@app.get("/new", response_class=HTMLResponse)
def new_session_form(request: Request) -> HTMLResponse:
    """Render the upload form for creating a new session."""
    return templates.TemplateResponse(
        request,
        "new.html",
        {"providers": PROVIDERS, "default_models": DEFAULT_MODELS},
    )


@app.post("/sessions")
async def create_session(
    background_tasks: BackgroundTasks,
    name: str = Form(...),
    provider: str = Form(...),
    model: str = Form(...),
    clips: list[UploadFile] = Form(...),
    music: UploadFile = Form(...),
) -> RedirectResponse:
    """Save uploaded media into a new session dir and launch the pipeline."""
    session_dir = SESSIONS_DIR / name
    inputs_dir = session_dir / "inputs"
    music_dir = session_dir / "music"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    music_dir.mkdir(parents=True, exist_ok=True)

    allowed_exts = VIDEO_EXTS | IMAGE_EXTS
    for clip in clips:
        filename = Path(clip.filename or "").name
        if Path(filename).suffix.lower() not in allowed_exts:
            continue
        with (inputs_dir / filename).open("wb") as f:
            shutil.copyfileobj(clip.file, f)

    with (music_dir / "track.mp3").open("wb") as f:
        shutil.copyfileobj(music.file, f)

    job = JobState()
    with _lock:
        _jobs[name] = job
    background_tasks.add_task(run_pipeline_job, session_dir, provider, model, job)

    return RedirectResponse(f"/sessions/{name}", status_code=303)


@app.get("/sessions/{name}", response_class=HTMLResponse)
def session_page(request: Request, name: str) -> HTMLResponse:
    """Show a session's live status, or its final results once done."""
    job = _jobs.get(name)
    reel_exists = (SESSIONS_DIR / name / "reel.mp4").exists()
    return templates.TemplateResponse(
        request,
        "session.html",
        {"name": name, "job": job, "reel_exists": reel_exists},
    )


@app.get("/sessions/{name}/status")
def session_status(name: str) -> dict:
    """JSON status for the polling script on the session page."""
    job = _jobs.get(name)
    if job is None:
        return {"stage": "unknown", "done": True, "error": None}
    return {"stage": job.stage, "done": job.done, "error": job.error}


@app.get("/sessions/{name}/reel.mp4")
def session_reel(name: str) -> FileResponse:
    """Serve the rendered reel for preview/download."""
    reel_path = SESSIONS_DIR / name / "reel.mp4"
    if not reel_path.exists():
        raise HTTPException(status_code=404)
    return FileResponse(reel_path, media_type="video/mp4")
