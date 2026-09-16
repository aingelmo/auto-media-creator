"""FastAPI app: local, no-auth JSON API + SPA static host for edl-agent.

Run with `uv run scripts/run_web.py`. Job progress is tracked in an
in-memory dict, so it does not survive a server restart -- fine for a
local, single-process, single-user tool (see `web/pipeline.py`). The
browser UI is a React SPA built into `web/static/` (see `frontend/`); this
module serves its JSON API under `/api/*` plus the built assets and raw
session files.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

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
STATIC_DIR = Path(__file__).parent / "static"

# Providers offered in the UI dropdown, deepseek first so it's the default
# selection; anthropic/gemini stay usable via PROVIDERS for non-UI callers.
UI_PROVIDERS = ("deepseek", "ollama")

# Provider -> env var read by edl_agent.llm.get_client; gemini/ollama use
# SDK-default/no-auth flows not worth preflighting here.
PROVIDER_API_KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}

app = FastAPI(title="edl-agent")

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


def _job_payload(job: JobState | None) -> dict[str, Any] | None:
    """Serialise a `JobState` to JSON, or `None` if there is no live job.

    `JobState` itself is not JSON-serialisable (it holds a
    `threading.Event`), so every field the frontend needs is picked out
    explicitly here.

    Args:
        job: Live job tracked in `_jobs`, or `None`.

    Returns:
        `None` if `job` is `None`, else a dict with the subset of
        `JobState` fields the session page reads.
    """
    if job is None:
        return None
    return {
        "stages": job.stages,
        "detail": job.detail,
        "done": job.done,
        "error": job.error,
        "awaiting_confirmation": job.awaiting_confirmation,
        "pause_kind": job.pause_kind,
        "check_results": job.check_results,
        "check_results_b": job.check_results_b,
        "unverified_sources": job.unverified_sources,
        "low_candidates": job.low_candidates,
        "hooks": job.hooks,
        "hook_slot": job.hook_slot,
        "music_candidates": job.music_candidates,
    }


@app.get("/api/sessions")
def list_sessions() -> list[dict]:
    """List existing sessions with their derived status."""
    dirs = SESSIONS_DIR.iterdir() if SESSIONS_DIR.exists() else []
    names = sorted(p.name for p in dirs if p.is_dir())
    return [{"name": n, "status": _session_status(n)} for n in names]


@app.get("/api/config")
def get_config() -> dict:
    """Providers/default-models for the new-session and regenerate forms."""
    return {"providers": UI_PROVIDERS, "default_models": DEFAULT_MODELS}


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


@app.post("/api/sessions")
async def create_session(
    background_tasks: BackgroundTasks,
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
    brief: str = Form(""),
    audience: str = Form("prospects"),
) -> JSONResponse:
    """Save uploaded media (+ optional brand logo) into a new session dir and launch."""
    key_env = PROVIDER_API_KEY_ENV.get(provider)
    if key_env and not os.environ.get(key_env):
        raise HTTPException(
            status_code=400,
            detail=f"{key_env} is not set in the server's environment. "
            f"Export it and restart the web server before running {provider}.",
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
        raise HTTPException(
            status_code=400,
            detail=(
                f"Music file must be one of {sorted(MUSIC_EXTS)}, got {music_ext!r}."
            ),
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
        brief=brief.strip(),
        audience=audience,
    )

    return JSONResponse({"name": name})


@app.post("/api/sessions/{name}/start")
def start_session(
    name: str,
    background_tasks: BackgroundTasks,
    provider: str = Form(...),
    model: str = Form(...),
    theme: str = Form("training"),
    hook_line: str = Form(""),
    brief: str = Form(""),
    audience: str = Form("prospects"),
) -> JSONResponse:
    """Launch the pipeline for a session whose inputs exist but never got a job.

    Covers a session directory left behind by a server restart (or a
    process that died) before any stage completed, so there's neither a
    live `JobState` for `/retry` nor a finished stage for `/regenerate`.
    """
    session_dir = SESSIONS_DIR / name
    if not session_dir.is_dir():
        raise HTTPException(status_code=404, detail="no such session")

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
        brief.strip(),
        audience,
    )

    return JSONResponse({"name": name})


@app.post("/api/sessions/{name}/retry")
def retry_session(name: str, background_tasks: BackgroundTasks) -> JSONResponse:
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
        old_job.brief,
        old_job.audience,
    )

    return JSONResponse({"name": name})


@app.post("/api/sessions/{name}/regenerate")
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
    brief: str = Form(""),
    audience: str = Form("prospects"),
) -> JSONResponse:
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
        brief.strip(),
        audience,
    )

    return JSONResponse({"name": name})


@app.get("/api/sessions/{name}")
def session_page(name: str) -> dict:
    """A session's live per-stage status, or its final results once done."""
    job = _jobs.get(name)
    reel_exists = (SESSIONS_DIR / name / "reel.mp4").exists()
    reel_b_exists = (SESSIONS_DIR / name / "reel_b.mp4").exists()
    stage_statuses = _stage_statuses(name)
    regen_stages = ("candidates", "selection", "hooks", "planner", "render")
    default_from_stage = next(
        (s for s in regen_stages if stage_statuses.get(s) == "pending"), "selection"
    )
    return {
        "name": name,
        "job": _job_payload(job),
        "reel_exists": reel_exists,
        "reel_b_exists": reel_b_exists,
        "stages": STAGES,
        "stage_statuses": stage_statuses,
        "providers": UI_PROVIDERS,
        "default_models": DEFAULT_MODELS,
        "default_from_stage": default_from_stage,
    }


@app.get("/api/sessions/{name}/status")
def session_status(name: str) -> dict:
    """JSON status for the polling script on the session page."""
    job = _jobs.get(name)
    if job is None:
        return {
            "stages": _stage_statuses(name),
            "detail": {},
            "done": True,
            "error": None,
            "awaiting_confirmation": False,
            "pause_kind": "",
        }
    return {
        "stages": job.stages,
        "detail": job.detail,
        "done": job.done,
        "error": job.error,
        "awaiting_confirmation": job.awaiting_confirmation,
        "pause_kind": job.pause_kind,
    }


@app.post("/api/sessions/{name}/confirm")
def session_confirm(
    name: str,
    proceed: bool = Form(...),
    exclude: list[str] = Form(default=[]),
    shorten: bool = Form(default=False),
    hook_line: str = Form(""),
    hook_custom: str = Form(""),
    hook_line_b: str = Form(""),
    hook_flash: bool = Form(default=False),
    more: bool = Form(default=False),
    music_offset: float = Form(0.0),
    more_music: bool = Form(default=False),
) -> JSONResponse:
    """Unblock a job paused on `awaiting_confirmation` (see `JobState`).

    `proceed=False` cancels the run instead of continuing. For a
    `"music_choice"` pause, `music_offset` picks the candidate cut to use,
    and `more_music=True` generates another batch of candidates instead of
    proceeding. For a `"verification"` pause, any `exclude` source paths
    (checked on the confirmation form) are dropped from the manifest. For a
    `"low_candidates"` pause, `shorten=True` re-cuts the music to the
    suggested shorter duration instead of keeping the original one. For a
    `"hook_choice"` pause, `hook_custom` (if non-empty) wins over the
    selected `hook_line` radio value, `hook_line_b` (idea #7) picks the
    hook line for a second variant reel (`""` = no variant B), `hook_flash`
    (checked by default in the frontend) toggles the hook's white flash,
    and `more=True` regenerates a fresh batch of 3 lines instead of
    proceeding to the final render.
    """
    job = _jobs.get(name)
    if job is None or not job.awaiting_confirmation:
        raise HTTPException(status_code=404, detail="no confirmation pending")
    job.cancelled = not proceed
    job.excluded_sources = exclude
    job.shorten = shorten
    job.hook_choice = hook_custom.strip() or hook_line
    job.hook_choice_b = hook_line_b
    job.hook_flash = hook_flash
    job.more_hooks = more
    job.music_choice_offset = music_offset
    job.more_music = more_music
    job.confirm_event.set()
    return JSONResponse({"name": name})


@app.get("/sessions/{name}/reel.mp4")
def session_reel(name: str) -> FileResponse:
    """Serve the rendered reel for preview/download."""
    reel_path = SESSIONS_DIR / name / "reel.mp4"
    if not reel_path.exists():
        raise HTTPException(status_code=404)
    return FileResponse(reel_path, media_type="video/mp4")


@app.get("/sessions/{name}/files/{path:path}")
def session_file(name: str, path: str) -> FileResponse:
    """Serve a session-relative file for debug views."""
    session_dir = (SESSIONS_DIR / name).resolve()
    file_path = (session_dir / path).resolve()
    if session_dir not in file_path.parents or not file_path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(file_path)


@app.get("/api/sessions/{name}/ingest")
def ingest_page(name: str) -> dict:
    """`manifest.json`'s sources for debugging the ingest stage."""
    return _load_json(name, "manifest.json")


@app.get("/api/sessions/{name}/candidates")
def candidates_page(name: str) -> dict:
    """`candidates.json` with thumbnail URLs for debugging selection input."""
    session_dir = SESSIONS_DIR / name
    payload = _load_json(name, "candidates.json")
    candidates = payload["candidates"]
    for c in candidates:
        c["peak_urls"] = [
            f"/sessions/{name}/files/{Path(jpg).resolve().relative_to(session_dir.resolve())}"
            for jpg in c["peak_frames"]
        ]
    return {"candidates": candidates}


@app.get("/api/sessions/{name}/selection")
def selection_page(name: str) -> dict:
    """Every `selection_attempt_N.json` -- prompt, raw LLM reply, usage, cost."""
    session_dir = SESSIONS_DIR / name
    attempts = sorted(session_dir.glob("selection_attempt_*.json"))
    if not attempts:
        raise HTTPException(status_code=404, detail="no selection attempts yet")
    return {"attempts": [json.loads(p.read_text()) for p in attempts]}


@app.get("/api/sessions/{name}/planner")
def planner_page(name: str) -> dict:
    """`edl.json`'s clip list for debugging the planner stage."""
    return _load_json(name, "edl.json")


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
