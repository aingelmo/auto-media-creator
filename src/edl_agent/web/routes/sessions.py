"""Session CRUD, lifecycle (start/retry/regenerate), status, and confirmation."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from edl_agent.paths import SESSIONS_DIR
from edl_agent.selection.s_checks import clean_hook_line
from edl_agent.session._common import IMAGE_EXTS, MUSIC_EXTS, VIDEO_EXTS
from edl_agent.web.artifacts import clear_stage_artifacts
from edl_agent.web.pipeline import (
    DEFAULT_MODELS,
    DISPLAY_STAGES,
    STAGES,
    JobState,
    run_pipeline_job,
)
from edl_agent.web.routes.config import save_brand
from edl_agent.web.state import (
    PROVIDER_API_KEY_ENV,
    UI_PROVIDERS,
    append_history,
    job_payload,
    jobs,
    lock,
    read_history,
    session_status,
    stage_statuses,
    total_cost_usd,
)

router = APIRouter()


@router.get("/api/sessions")
def list_sessions() -> list[dict]:
    """List existing sessions with their derived status and intake summary.

    Returns:
        One dict per session directory with `name`, `status` (see
        `state.session_status`), `reel_exists`, `clip_count` (video/image
        files under `inputs/`), `music_name` (first track under `music/`,
        excluding the generated `track_cut.wav`), `total_cost_usd`, and
        `mtime` (session directory mtime, for recency sorting).
    """
    if not SESSIONS_DIR.exists():
        return []
    allowed = VIDEO_EXTS | IMAGE_EXTS
    out = []
    for p in sorted(p.name for p in SESSIONS_DIR.iterdir() if p.is_dir()):
        sdir = SESSIONS_DIR / p
        inputs = sdir / "inputs"
        clip_count = (
            sum(
                1
                for f in inputs.iterdir()
                if f.is_file() and f.suffix.lower() in allowed
            )
            if inputs.is_dir()
            else 0
        )
        music_dir = sdir / "music"
        music_name = ""
        if music_dir.is_dir():
            tracks = sorted(
                f.name
                for f in music_dir.iterdir()
                if f.is_file()
                and f.suffix.lower() in MUSIC_EXTS
                and f.name != "track_cut.wav"
            )
            music_name = tracks[0] if tracks else ""
        try:
            mtime = sdir.stat().st_mtime
        except OSError:
            mtime = 0.0
        out.append(
            {
                "name": p,
                "status": session_status(p),
                "reel_exists": (sdir / "reel.mp4").exists(),
                "clip_count": clip_count,
                "music_name": music_name,
                "total_cost_usd": total_cost_usd(p),
                "mtime": mtime,
            }
        )
    return out


def _link_ref(ref: str, dest_dir: Path, dest_name: str) -> None:
    """Symlink a `"{session}/{path}"` picker ref into `dest_dir/dest_name`.

    Mirrors `ingest.cache.link_into`'s symlink-to-resolved-absolute-path
    pattern. Raises 400/404 if the ref doesn't resolve to a real file
    inside `SESSIONS_DIR` (same containment check as
    `routes/files.py:session_file`).
    """
    ref_session, _, ref_path = ref.partition("/")
    if not ref_session or not ref_path:
        raise HTTPException(status_code=400, detail=f"malformed media ref {ref!r}")
    src_dir = (SESSIONS_DIR / ref_session).resolve()
    src_path = (src_dir / ref_path).resolve()
    sessions_root = SESSIONS_DIR.resolve()
    # Resolves through any chained symlinks (a ref picked from a session that
    # itself picked it from an earlier one), so containment is checked against
    # SESSIONS_DIR as a whole, not the single ref_session subtree.
    if sessions_root not in src_path.parents or not src_path.is_file():
        raise HTTPException(status_code=404, detail=f"no such media {ref!r}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / dest_name
    if dest.is_symlink() and dest.resolve() == src_path:
        return
    stem, suffix = Path(dest_name).stem, Path(dest_name).suffix
    n = 1
    while dest.exists():
        dest = dest_dir / f"{stem}_{n}{suffix}"
        n += 1
    dest.symlink_to(src_path)


@router.post("/api/sessions")
async def create_session(
    background_tasks: BackgroundTasks,
    name: str = Form(...),
    provider: str = Form(...),
    theme: str = Form("training"),
    clips: list[UploadFile] = Form([]),
    music: UploadFile | None = None,
    clip_refs: list[str] = Form([]),
    music_ref: str = Form(""),
    logo: UploadFile | None = None,
    handle: str = Form(""),
    brief: str = Form(""),
    audience: str = Form("prospects"),
) -> JSONResponse:
    """Save uploaded/picked media (+ optional brand logo), then launch the pipeline.

    Clips/music can come from a fresh upload (`clips`/`music`) and/or be
    picked from a past session's already-on-disk files (`clip_refs`/
    `music_ref`, each `"{session}/{path}"` from `GET /api/media`) — the two
    are symlinked/copied together into the new session's `inputs`/`music`.
    """
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
    clip_count = 0
    for clip in clips:
        filename = Path(clip.filename or "").name
        if not filename or Path(filename).suffix.lower() not in allowed_exts:
            continue
        with (inputs_dir / filename).open("wb") as f:
            shutil.copyfileobj(clip.file, f)
        clip_count += 1
    for ref in clip_refs:
        _link_ref(ref, inputs_dir, Path(ref).name)
        clip_count += 1
    if clip_count == 0:
        raise HTTPException(status_code=400, detail="at least one clip is required")

    have_music = False
    if music is not None and music.filename:
        music_ext = Path(music.filename).suffix.lower()
        if music_ext not in MUSIC_EXTS:
            raise HTTPException(
                status_code=400,
                detail=f"Music must be one of {sorted(MUSIC_EXTS)}, got {music_ext!r}.",
            )
        music_name = Path(music.filename).name
        with (music_dir / music_name).open("wb") as f:
            shutil.copyfileobj(music.file, f)
        have_music = True
    elif music_ref:
        _link_ref(music_ref, music_dir, Path(music_ref).name)
        have_music = True
    if not have_music:
        raise HTTPException(status_code=400, detail="a music track is required")

    save_brand(session_dir, logo, handle)

    job = JobState()
    with lock:
        jobs[name] = job
    background_tasks.add_task(
        run_pipeline_job,
        session_dir,
        provider,
        DEFAULT_MODELS[provider],
        job,
        theme=theme,
        brief=brief.strip(),
        audience=audience,
    )

    return JSONResponse({"name": name})


@router.post("/api/sessions/{name}/start")
def start_session(
    name: str,
    background_tasks: BackgroundTasks,
    provider: str = Form(...),
    theme: str = Form("training"),
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
    with lock:
        jobs[name] = job
    background_tasks.add_task(
        run_pipeline_job,
        session_dir,
        provider,
        DEFAULT_MODELS[provider],
        job,
        resume=True,
        theme=theme,
        brief=brief.strip(),
        audience=audience,
    )

    return JSONResponse({"name": name})


@router.post("/api/sessions/{name}/retry")
def retry_session(name: str, background_tasks: BackgroundTasks) -> JSONResponse:
    """Relaunch a failed session's pipeline, resuming past stages already on disk."""
    old_job = jobs.get(name)
    if old_job is None or not old_job.error:
        raise HTTPException(status_code=404, detail="no failed run to retry")

    job = JobState()
    with lock:
        jobs[name] = job
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


@router.post("/api/sessions/{name}/regenerate")
def regenerate_session(
    name: str,
    background_tasks: BackgroundTasks,
    from_stage: str = Form(...),
    provider: str = Form(...),
    theme: str = Form("training"),
    logo: UploadFile | None = None,
    handle: str = Form(""),
    hook_line: str = Form(""),
    brief: str = Form(""),
    audience: str = Form("prospects"),
) -> JSONResponse:
    """Force `from_stage` onward to redo, reusing already-completed earlier stages.

    A new logo replaces the session brand; it only takes effect from `planner`
    on, so the stage is pulled back to `planner` if a later one was chosen.
    Any regenerate that reaches the `render` stage re-pauses on
    `"effects_preview"` (see `session_confirm`), so `hook_flash`/`punch_in`
    aren't regenerate-form fields -- they're picked there instead.
    """
    session_dir = SESSIONS_DIR / name
    if not session_dir.is_dir():
        raise HTTPException(status_code=404, detail="no such session")
    if from_stage not in STAGES:
        raise HTTPException(status_code=400, detail=f"unknown stage {from_stage!r}")

    brand_updated = logo is not None and bool(logo.filename)
    if brand_updated:
        save_brand(session_dir, logo, handle)
        if STAGES.index(from_stage) > STAGES.index("planner"):
            from_stage = "planner"
    clear_stage_artifacts(session_dir, from_stage)
    append_history(
        name,
        {
            "from_stage": from_stage,
            "provider": provider,
            "model": DEFAULT_MODELS[provider],
            "theme": theme,
            "audience": audience,
            "brief": brief.strip(),
            "hook_line": clean_hook_line(hook_line),
            "brand_updated": brand_updated,
        },
    )

    job = JobState()
    with lock:
        jobs[name] = job
    background_tasks.add_task(
        run_pipeline_job,
        session_dir,
        provider,
        DEFAULT_MODELS[provider],
        job,
        True,
        theme,
        clean_hook_line(hook_line),
        brief.strip(),
        audience,
    )

    return JSONResponse({"name": name})


@router.get("/api/sessions/{name}")
def session_page(name: str) -> dict:
    """A session's live per-stage status, or its final results once done."""
    job = jobs.get(name)
    reel_exists = (SESSIONS_DIR / name / "reel.mp4").exists()
    reel_b_exists = (SESSIONS_DIR / name / "reel_b.mp4").exists()
    statuses = stage_statuses(name)
    regen_stages = ("candidates", "selection", "planner", "hooks", "render")
    default_from_stage = next(
        (s for s in regen_stages if statuses.get(s) == "pending"), "selection"
    )
    return {
        "name": name,
        "job": job_payload(job),
        "reel_exists": reel_exists,
        "reel_b_exists": reel_b_exists,
        "stages": DISPLAY_STAGES,
        "stage_statuses": statuses,
        "providers": UI_PROVIDERS,
        "default_models": DEFAULT_MODELS,
        "default_from_stage": default_from_stage,
        "history": read_history(name),
        "total_cost_usd": total_cost_usd(name),
    }


@router.get("/api/sessions/{name}/status")
def session_status_endpoint(name: str) -> dict:
    """JSON status for the polling script on the session page."""
    job = jobs.get(name)
    if job is None:
        return {
            "stages": stage_statuses(name),
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


@router.post("/api/sessions/{name}/confirm")
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
    punch_in: bool = Form(default=False),
    effects_preview_again: bool = Form(default=False),
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
    selected `hook_line` radio value and `hook_line_b` (idea #7) picks the
    hook line for a second variant reel (`""` = no variant B); both are
    manual text or none, since the web `hooks` stage never calls the
    hook-copy LLM (`more` is ignored there). For an `"effects_preview"`
    pause, `hook_flash` toggles the hook's white flash, `punch_in` toggles
    the develop-clip punch-in zoom, and `effects_preview_again=True`
    rebuilds the EDL and re-renders the preview instead of proceeding to
    the full-resolution render.
    """
    job = jobs.get(name)
    if job is None or not job.awaiting_confirmation:
        raise HTTPException(status_code=404, detail="no confirmation pending")
    job.cancelled = not proceed
    job.excluded_sources = exclude
    job.shorten = shorten
    if job.pause_kind == "hook_choice":
        job.hook_choice = hook_custom.strip() or hook_line
        job.hook_choice_b = hook_line_b
        job.more_hooks = False
    else:
        job.more_hooks = more
    job.hook_flash = hook_flash
    job.music_choice_offset = music_offset
    job.punch_in = punch_in
    job.effects_preview_again = effects_preview_again
    job.more_music = more_music
    job.confirm_event.set()
    return JSONResponse({"name": name})
