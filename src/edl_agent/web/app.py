"""FastAPI app: local, no-auth UI for running edl-agent sessions.

Run with `uv run scripts/run_web.py`. Job progress is tracked in an
in-memory dict, so it does not survive a server restart -- fine for a
local, single-process, single-user tool (see `web/pipeline.py`).
"""

from __future__ import annotations

import json
import os
import shutil
import threading
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from edl_agent.llm import PROVIDERS
from edl_agent.selection.s_checks import clean_hook_line
from edl_agent.session._common import IMAGE_EXTS, MUSIC_EXTS, VIDEO_EXTS
from edl_agent.web.pipeline import (
    DEFAULT_MODELS,
    STAGES,
    JobState,
    clear_stage_artifacts,
    run_pipeline_job,
)

SESSIONS_DIR = Path("sessions")
TEMPLATES_DIR = Path(__file__).parent / "templates"

# Provider -> env var read by edl_agent.llm.get_client; gemini/ollama use
# SDK-default/no-auth flows not worth preflighting here.
PROVIDER_API_KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}

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


def _stage_statuses(name: str) -> dict[str, str]:
    """Per-stage status for a session's checklist, live job or disk fallback.

    Args:
        name: Session directory name under `SESSIONS_DIR`.

    Returns:
        Dict keyed by `STAGES`. If a live `JobState` is tracked, its
        `stages` dict is used directly. Otherwise (server restarted since
        the run), status is derived from which artifact files exist on
        disk: `"done"` if the stage's output file exists, `"pending"`
        otherwise -- a run from a previous process has no "running"/"failed"
        signal available.
    """
    job = _jobs.get(name)
    if job is not None:
        return job.stages
    session_dir = SESSIONS_DIR / name
    artifact_by_stage = {
        "ingest": "manifest.json",
        "candidates": "candidates.json",
        "selection": "selection.json",
        "hooks": "hooks.json",
        "planner": "edl.json",
        "render": "reel.mp4",
        "checks": "reel.mp4",
    }
    return {
        stage: "done"
        if (session_dir / artifact_by_stage[stage]).exists()
        else "pending"
        for stage in STAGES
    }


def _load_json(name: str, filename: str) -> dict:
    """Read and parse a session artifact JSON file, or 404.

    Args:
        name: Session directory name under `SESSIONS_DIR`.
        filename: File name within the session directory.

    Returns:
        Parsed JSON content.

    Raises:
        HTTPException: 404 if the file doesn't exist yet.
    """
    path = SESSIONS_DIR / name / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{filename} not found yet")
    return json.loads(path.read_text())


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
        {"providers": PROVIDERS, "default_models": DEFAULT_MODELS, "error": None},
    )


def _save_brand(
    session_dir: Path, logo: UploadFile | None, handle: str, line: str
) -> None:
    """Write `brand/{logo.png,brand.json}` if a logo was uploaded; else leave as is.

    Per-session brand (#6.8): one business per session, nothing repo-level.
    """
    if logo is None or not logo.filename:
        return
    brand_dir = session_dir / "brand"
    brand_dir.mkdir(exist_ok=True)
    with (brand_dir / "logo.png").open("wb") as f:
        shutil.copyfileobj(logo.file, f)
    (brand_dir / "brand.json").write_text(
        json.dumps(
            {"logo": "brand/logo.png", "handle": handle.strip(), "line": line.strip()},
            ensure_ascii=False,
            indent=2,
        )
    )


@app.post("/sessions", response_model=None)
async def create_session(
    background_tasks: BackgroundTasks,
    request: Request,
    name: str = Form(...),
    provider: str = Form(...),
    model: str = Form(...),
    theme: str = Form("training"),
    clips: list[UploadFile] = Form(...),
    music: UploadFile = Form(...),
    logo: UploadFile | None = None,
    handle: str = Form(""),
    line: str = Form(""),
    hook_line: str = Form(""),
) -> HTMLResponse | RedirectResponse:
    """Save uploaded media (+ optional brand logo) into a new session dir and launch."""
    key_env = PROVIDER_API_KEY_ENV.get(provider)
    if key_env and not os.environ.get(key_env):
        return templates.TemplateResponse(
            request,
            "new.html",
            {
                "providers": PROVIDERS,
                "default_models": DEFAULT_MODELS,
                "error": f"{key_env} is not set in the server's environment. "
                f"Export it and restart the web server before running {provider}.",
            },
            status_code=400,
        )

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

    music_ext = Path(music.filename or "").suffix.lower()
    if music_ext not in MUSIC_EXTS:
        return templates.TemplateResponse(
            request,
            "new.html",
            {
                "providers": PROVIDERS,
                "default_models": DEFAULT_MODELS,
                "error": (
                    f"Music file must be one of {sorted(MUSIC_EXTS)}, "
                    f"got {music_ext!r}."
                ),
            },
            status_code=400,
        )
    with (music_dir / f"track{music_ext}").open("wb") as f:
        shutil.copyfileobj(music.file, f)

    _save_brand(session_dir, logo, handle, line)

    job = JobState()
    with _lock:
        _jobs[name] = job
    background_tasks.add_task(
        run_pipeline_job,
        session_dir,
        provider,
        model,
        job,
        theme=theme,
        hook_line_override=clean_hook_line(hook_line),
    )

    return RedirectResponse(f"/sessions/{name}", status_code=303)


@app.post("/sessions/{name}/retry", response_model=None)
def retry_session(name: str, background_tasks: BackgroundTasks) -> RedirectResponse:
    """Relaunch a failed session's pipeline, resuming past stages already on disk."""
    old_job = _jobs.get(name)
    if old_job is None or not old_job.error:
        raise HTTPException(status_code=404, detail="no failed run to retry")

    job = JobState()
    with _lock:
        _jobs[name] = job
    background_tasks.add_task(
        run_pipeline_job,
        SESSIONS_DIR / name,
        old_job.provider,
        old_job.model,
        job,
        True,
        old_job.theme,
        old_job.hook_line_override,
    )

    return RedirectResponse(f"/sessions/{name}", status_code=303)


@app.post("/sessions/{name}/regenerate", response_model=None)
def regenerate_session(
    name: str,
    background_tasks: BackgroundTasks,
    from_stage: str = Form(...),
    provider: str = Form(...),
    model: str = Form(...),
    theme: str = Form("training"),
    logo: UploadFile | None = None,
    handle: str = Form(""),
    line: str = Form(""),
    hook_line: str = Form(""),
) -> RedirectResponse:
    """Force `from_stage` onward to redo, reusing already-completed earlier stages.

    A new logo replaces the session brand; it only takes effect from `planner`
    on, so the stage is pulled back to `planner` if a later one was chosen.
    """
    session_dir = SESSIONS_DIR / name
    if not session_dir.is_dir():
        raise HTTPException(status_code=404, detail="no such session")
    if from_stage not in STAGES:
        raise HTTPException(status_code=400, detail=f"unknown stage {from_stage!r}")

    if logo is not None and logo.filename:
        _save_brand(session_dir, logo, handle, line)
        if STAGES.index(from_stage) > STAGES.index("planner"):
            from_stage = "planner"
    clear_stage_artifacts(session_dir, from_stage)

    job = JobState()
    with _lock:
        _jobs[name] = job
    background_tasks.add_task(
        run_pipeline_job,
        session_dir,
        provider,
        model,
        job,
        True,
        theme,
        clean_hook_line(hook_line),
    )

    return RedirectResponse(f"/sessions/{name}", status_code=303)


@app.get("/sessions/{name}", response_class=HTMLResponse)
def session_page(request: Request, name: str) -> HTMLResponse:
    """Show a session's live per-stage status, or its final results once done."""
    job = _jobs.get(name)
    reel_exists = (SESSIONS_DIR / name / "reel.mp4").exists()
    reel_b_exists = (SESSIONS_DIR / name / "reel_b.mp4").exists()
    return templates.TemplateResponse(
        request,
        "session.html",
        {
            "name": name,
            "job": job,
            "reel_exists": reel_exists,
            "reel_b_exists": reel_b_exists,
            "stages": STAGES,
            "stage_statuses": _stage_statuses(name),
            "providers": PROVIDERS,
            "default_models": DEFAULT_MODELS,
        },
    )


@app.get("/sessions/{name}/status")
def session_status(name: str) -> dict:
    """JSON status for the polling script on the session page."""
    job = _jobs.get(name)
    if job is None:
        return {
            "stages": _stage_statuses(name),
            "done": True,
            "error": None,
            "awaiting_confirmation": False,
        }
    return {
        "stages": job.stages,
        "done": job.done,
        "error": job.error,
        "awaiting_confirmation": job.awaiting_confirmation,
    }


@app.post("/sessions/{name}/confirm", response_model=None)
def session_confirm(
    name: str,
    proceed: bool = Form(...),
    exclude: list[str] = Form(default=[]),
    shorten: bool = Form(default=False),
    hook_line: str = Form(""),
    hook_custom: str = Form(""),
    hook_line_b: str = Form(""),
    more: bool = Form(default=False),
) -> RedirectResponse:
    """Unblock a job paused on `awaiting_confirmation` (see `JobState`).

    `proceed=False` cancels the run instead of continuing. For a
    `"verification"` pause, any `exclude` source paths (checked on the
    confirmation form) are dropped from the manifest. For a
    `"low_candidates"` pause, `shorten=True` re-cuts the music to the
    suggested shorter duration instead of keeping the original one. For a
    `"hook_choice"` pause, `hook_custom` (if non-empty) wins over the
    selected `hook_line` radio value, `hook_line_b` (idea #7) picks the
    hook line for a second variant reel (`""` = no variant B), and
    `more=True` regenerates a fresh batch of 6 lines instead of proceeding
    to the final render.
    """
    job = _jobs.get(name)
    if job is None or not job.awaiting_confirmation:
        raise HTTPException(status_code=404, detail="no confirmation pending")
    job.cancelled = not proceed
    job.excluded_sources = exclude
    job.shorten = shorten
    job.hook_choice = hook_custom.strip() or hook_line
    job.hook_choice_b = hook_line_b
    job.more_hooks = more
    job.confirm_event.set()
    return RedirectResponse(f"/sessions/{name}", status_code=303)


@app.get("/sessions/{name}/reel.mp4")
def session_reel(name: str) -> FileResponse:
    """Serve the rendered reel for preview/download."""
    reel_path = SESSIONS_DIR / name / "reel.mp4"
    if not reel_path.exists():
        raise HTTPException(status_code=404)
    return FileResponse(reel_path, media_type="video/mp4")


@app.get("/sessions/{name}/files/{path:path}")
def session_file(name: str, path: str) -> FileResponse:
    """Serve a session-relative file (peak frames, proxies, segments) for debug views."""
    session_dir = (SESSIONS_DIR / name).resolve()
    file_path = (session_dir / path).resolve()
    if session_dir not in file_path.parents or not file_path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(file_path)


@app.get("/sessions/{name}/ingest", response_class=HTMLResponse)
def ingest_page(request: Request, name: str) -> HTMLResponse:
    """Show `manifest.json`'s sources for debugging the ingest stage."""
    manifest = _load_json(name, "manifest.json")
    return templates.TemplateResponse(
        request, "ingest.html", {"name": name, "manifest": manifest}
    )


@app.get("/sessions/{name}/candidates", response_class=HTMLResponse)
def candidates_page(request: Request, name: str) -> HTMLResponse:
    """Show `candidates.json` with peak-frame thumbnails for debugging selection input."""
    session_dir = SESSIONS_DIR / name
    payload = _load_json(name, "candidates.json")
    candidates = payload["candidates"]
    for c in candidates:
        c["peak_urls"] = [
            f"/sessions/{name}/files/{Path(jpg).resolve().relative_to(session_dir.resolve())}"
            for jpg in c["peak_frames"]
        ]
    return templates.TemplateResponse(
        request, "candidates.html", {"name": name, "candidates": candidates}
    )


@app.get("/sessions/{name}/selection", response_class=HTMLResponse)
def selection_page(request: Request, name: str) -> HTMLResponse:
    """Show every `selection_attempt_N.json` -- prompt, raw LLM reply, usage, cost."""
    session_dir = SESSIONS_DIR / name
    attempts = sorted(session_dir.glob("selection_attempt_*.json"))
    if not attempts:
        raise HTTPException(status_code=404, detail="no selection attempts yet")
    records = [json.loads(p.read_text()) for p in attempts]
    return templates.TemplateResponse(
        request, "selection.html", {"name": name, "attempts": records}
    )


@app.get("/sessions/{name}/planner", response_class=HTMLResponse)
def planner_page(request: Request, name: str) -> HTMLResponse:
    """Show `edl.json`'s clip list for debugging the planner stage."""
    edl = _load_json(name, "edl.json")
    return templates.TemplateResponse(
        request, "planner.html", {"name": name, "edl": edl}
    )
