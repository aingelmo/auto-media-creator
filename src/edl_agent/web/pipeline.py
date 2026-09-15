"""Background pipeline runner for the web UI, mirroring scripts/run_e2e.py."""

from __future__ import annotations

import json
import shutil
import threading
import traceback
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from edl_agent.candidates import readmit_candidates
from edl_agent.features import yolo_pose_detector
from edl_agent.ingest import cut_music, sha256_file, write_manifest
from edl_agent.llm import get_client
from edl_agent.render import (
    concat_and_audio,
    render_hook_previews,
    render_preview_segments,
    render_segments,
    run_render_checks,
)
from edl_agent.selection.s_checks import clean_hook_line
from edl_agent.session import (
    run_candidates,
    run_hooks,
    run_ingest,
    run_planner,
    run_selection,
    tonemap_chain_for_manifest,
)
from edl_agent.slots import slots_from_file

if TYPE_CHECKING:
    from pathlib import Path

POSE_MODEL = "models/yolov8n-pose.pt"
THREADS = 4
MUSIC_OFFSET_S = 15.0
MUSIC_MAX_DURATION_S = 15.0
MIN_SHORTEN_DURATION_S = 5.0
SHORTEN_ATTEMPTS = 4  # beat detection isn't linear in duration; try progressively


def _shorten_durations(start_s: float) -> list[float]:
    """Decreasing durations to try when shortening, from `start_s` down to `MIN_SHORTEN_DURATION_S`.

    Beat detection doesn't scale slot count linearly with duration, so a
    single guessed duration isn't reliable; each step is retried against the
    real slot count until one produces few enough slots (see the
    `"low_candidates"` pause in `run_pipeline_job`).
    """
    if start_s <= MIN_SHORTEN_DURATION_S:
        return [MIN_SHORTEN_DURATION_S]
    step = (start_s - MIN_SHORTEN_DURATION_S) / (SHORTEN_ATTEMPTS - 1)
    return [round(start_s - i * step, 1) for i in range(SHORTEN_ATTEMPTS)]


DEFAULT_MODELS = {
    "gemini": "gemini-3.8-flash",
    "anthropic": "claude-sonnet-5",
    "deepseek": "deepseek-flash",
    "ollama": "qwen3-vl:8b-instruct",
}

STAGES = (
    "ingest",
    "candidates",
    "selection",
    "hooks",
    "planner",
    "render",
    "checks",
)

# Files/dirs (relative to a session dir) each stage writes, used by
# `clear_stage_artifacts` to force a stage to redo under `resume=True`.
# `ingest` is omitted: forcing it to redo also needs re-running the
# verification pause flow, which the regenerate form doesn't drive.
STAGE_ARTIFACTS = {
    "candidates": ["candidates.json"],
    "selection": ["selection.json", "selection_meta.json"],
    "hooks": ["hooks.json", "hook_previews"],
    "planner": ["edl.json"],
    "render": ["reel.mp4", "segments", "preview_segments"],
    "checks": [],
}


def clear_stage_artifacts(session_dir: Path, from_stage: str) -> None:
    """Delete `from_stage`'s and every later stage's output, so `resume=True` redoes them.

    Backs up an existing `reel.mp4` to `reel.prev.mp4` before deleting it.

    Args:
        session_dir: Session directory to clear artifacts in.
        from_stage: First stage (in `STAGES` order) to force a redo of.
    """
    reel_path = session_dir / "reel.mp4"
    if reel_path.exists():
        shutil.copy(reel_path, session_dir / "reel.prev.mp4")

    for stage in STAGES[STAGES.index(from_stage) :]:
        for rel_path in STAGE_ARTIFACTS.get(stage, []):
            path = session_dir / rel_path
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)


@dataclass
class JobState:
    """Progress/result tracker for one session's background pipeline run.

    Attributes:
        stages: Status of each `STAGES` entry: `"pending"`, `"running"`,
            `"done"`, or `"failed"`.
        error: Traceback string if the job failed, `None` otherwise.
        done: `True` once the job has finished (successfully or not).
        check_results: Stringified `run_render_checks` results, once the
            `checks` stage completes.
        unverified_sources: Video `src` paths whose proxy failed temporal
            verification against the original, once `ingest` completes.
        awaiting_confirmation: `True` while the job is paused waiting on
            `confirm_event`, either after `ingest` (`unverified_sources`
            non-empty) or after `candidates` (`low_candidates` non-empty).
        pause_kind: Which pause `awaiting_confirmation` refers to:
            `"verification"`, `"low_candidates"`, or `"hook_choice"`.
        confirm_event: Set (via `/sessions/{name}/confirm`) to unblock a
            job paused on `awaiting_confirmation`.
        cancelled: `True` if the user chose not to proceed past the
            `awaiting_confirmation` pause.
        excluded_sources: `src` paths (a subset of `unverified_sources`,
            set via `/sessions/{name}/confirm`) to drop from the manifest
            before resuming past a `"verification"` pause.
        low_candidates: `{"real_sources": int, "slot_count": int,
            "suggested_duration_s": float}` once `candidates` completes, if
            distinct usable video sources are fewer than slots to fill;
            `{}` otherwise.
        shorten: `True` (set via `/sessions/{name}/confirm`) to re-cut the
            music to `low_candidates["suggested_duration_s"]` and rebuild
            slots before resuming past a `"low_candidates"` pause; `False`
            keeps the original duration as-is.
        provider: LLM provider this job was (or should be, on retry) run
            with; kept so `/sessions/{name}/retry` can relaunch it.
        model: LLM model this job was (or should be, on retry) run with.
        theme: Selector prompt theme (`"training"` | `"yoga"`).
        hooks: Latest `hooks.json["lines"]` (`[{"angle", "text"}, ...]`),
            for the hook-choice template.
        hook_slot: Slot number of the hook clip, so the template can build
            preview URLs (`hook_previews/{key}/seg_{hook_slot:02d}.mp4`).
        hook_choice: Chosen/custom hook text (`""` = no text), set via
            `/sessions/{name}/confirm` during a `"hook_choice"` pause.
        more_hooks: `True` (set via `/sessions/{name}/confirm`) to
            generate a fresh batch of 6 lines instead of proceeding to the
            final render.
    """

    stages: dict[str, str] = field(
        default_factory=lambda: dict.fromkeys(STAGES, "pending")
    )
    error: str | None = None
    done: bool = False
    check_results: list[str] = field(default_factory=list)
    unverified_sources: list[str] = field(default_factory=list)
    awaiting_confirmation: bool = False
    pause_kind: str = ""
    confirm_event: threading.Event = field(default_factory=threading.Event)
    cancelled: bool = False
    excluded_sources: list[str] = field(default_factory=list)
    low_candidates: dict = field(default_factory=dict)
    shorten: bool = False
    provider: str = ""
    model: str = ""
    theme: str = "training"
    hooks: list[dict] = field(default_factory=list)
    hook_slot: int = 0
    hook_choice: str = ""
    more_hooks: bool = False

    @contextmanager
    def running(self, stage: str):  # noqa: ANN201 (contextmanager)
        """Mark `stage` `"running"`, then `"done"`, or `"failed"` on exception."""
        self.stages[stage] = "running"
        try:
            yield
        except Exception:
            self.stages[stage] = "failed"
            raise
        else:
            self.stages[stage] = "done"


def run_pipeline_job(
    session_dir: Path,
    provider: str,
    model: str,
    job: JobState,
    resume: bool = False,
    theme: str = "training",
) -> None:
    """Run the full ingest->render pipeline for a session, updating `job` along the way.

    Mirrors `scripts/run_e2e.py`'s `main()`, using the same fixed defaults
    for threads/pose-model/music-cut/tonemap since the web form only
    exposes session media and LLM provider/model.

    Args:
        session_dir: Session directory, already populated with `inputs/`
            and `music/track.<mp3|wav>` by the upload handler.
        provider: LLM provider name, one of `edl_agent.llm.PROVIDERS`.
        model: LLM model name for `provider`.
        job: `JobState` instance to update in place; the caller keeps a
            reference to it for status polling.
        resume: If `True`, skip any stage whose output file already exists
            on disk (loading it instead), per `/sessions/{name}/retry`.
        theme: Selector prompt theme, a key of `edl_agent.selector.prompts.THEMES`.
    """
    job.provider = provider
    job.model = model
    job.theme = theme
    try:
        manifest_path = session_dir / "manifest.json"
        slots_path = session_dir / "slots.json"
        if resume and manifest_path.exists() and slots_path.exists():
            job.stages["ingest"] = "done"
            manifest = json.loads(manifest_path.read_text())
            slots = json.loads(slots_path.read_text())
        else:
            with job.running("ingest"):
                manifest = run_ingest(
                    session_dir,
                    threads=THREADS,
                    music_offset_s=MUSIC_OFFSET_S,
                    music_max_duration_s=MUSIC_MAX_DURATION_S,
                )
                slots = slots_from_file(str(session_dir / "music" / "track_cut.wav"))
                slots_json = json.dumps(slots, indent=2, ensure_ascii=False)
                slots_path.write_text(slots_json)

            job.unverified_sources = [
                s["src"]
                for s in manifest["sources"]
                if s.get("type") == "video" and not s.get("proxy_verified", True)
            ]
            if job.unverified_sources:
                job.pause_kind = "verification"
                job.awaiting_confirmation = True
                job.confirm_event.wait()
                job.confirm_event.clear()
                job.awaiting_confirmation = False
                if job.cancelled:
                    return
                if job.excluded_sources:
                    manifest["sources"] = [
                        s
                        for s in manifest["sources"]
                        if s["src"] not in job.excluded_sources
                    ]
                    write_manifest(manifest, session_dir / "manifest.json")

        candidates_path = session_dir / "candidates.json"
        if resume and candidates_path.exists():
            job.stages["candidates"] = "done"
            candidates = json.loads(candidates_path.read_text())
        else:
            with job.running("candidates"):
                detector = yolo_pose_detector(POSE_MODEL)
                candidates = run_candidates(
                    session_dir, manifest, slots, detector, pose_model_path=POSE_MODEL
                )

            real_sources = len(
                {
                    c["src"]
                    for c in candidates["candidates"]
                    if c["kind"] != "image" and c["admits_slots"]
                }
            )
            slot_count = len(slots["slots"])
            has_video_sources = any(
                s.get("type") == "video" for s in manifest["sources"]
            )
            if has_video_sources and real_sources < slot_count:
                job.low_candidates = {
                    "real_sources": real_sources,
                    "slot_count": slot_count,
                    "suggested_duration_s": max(
                        MIN_SHORTEN_DURATION_S,
                        round(MUSIC_MAX_DURATION_S * real_sources / slot_count, 1),
                    ),
                }
                job.pause_kind = "low_candidates"
                job.awaiting_confirmation = True
                job.confirm_event.wait()
                job.confirm_event.clear()
                job.awaiting_confirmation = False
                if job.cancelled:
                    return
                if job.shorten:
                    music = manifest["music"]
                    cut_path = session_dir / "music" / "track_cut.wav"
                    orig_track = session_dir / music["src"]

                    best_duration, best_slots = None, None
                    for new_duration in _shorten_durations(
                        job.low_candidates["suggested_duration_s"]
                    ):
                        cut_music(orig_track, cut_path, music["offset_s"], new_duration)
                        candidate_slots = slots_from_file(str(cut_path))
                        if best_slots is None or len(candidate_slots["slots"]) < len(
                            best_slots["slots"]
                        ):
                            best_duration, best_slots = new_duration, candidate_slots
                        if len(candidate_slots["slots"]) <= real_sources:
                            break

                    if new_duration != best_duration:
                        cut_music(
                            orig_track, cut_path, music["offset_s"], best_duration
                        )
                    slots = best_slots

                    music["max_duration_s"] = best_duration
                    music["cut_sha256"] = sha256_file(cut_path)
                    write_manifest(manifest, session_dir / "manifest.json")

                    slots_path.write_text(
                        json.dumps(slots, indent=2, ensure_ascii=False)
                    )

                    readmit_candidates(candidates["candidates"], slots["slots"])
                    candidates_path.write_text(
                        json.dumps(candidates, indent=2, ensure_ascii=False)
                    )

        selection_path = session_dir / "selection.json"
        selection_meta_path = session_dir / "selection_meta.json"
        if resume and selection_path.exists():
            job.stages["selection"] = "done"
            selection = json.loads(selection_path.read_text()) or None
            selection_meta = (
                json.loads(selection_meta_path.read_text())
                if selection_meta_path.exists()
                else {}
            )
        else:
            with job.running("selection"):
                client = get_client(provider)
                selection, selection_meta = run_selection(
                    session_dir,
                    candidates,
                    slots,
                    config={"model": model, "theme": theme},
                    client=client,
                )
                selection_path.write_text(
                    json.dumps(selection or {}, indent=2, ensure_ascii=False)
                )
                selection_meta_path.write_text(
                    json.dumps(selection_meta or {}, indent=2, ensure_ascii=False)
                )

        edl_path = session_dir / "edl.json"
        tonemap_chain = tonemap_chain_for_manifest(manifest)
        if resume and edl_path.exists():
            job.stages["hooks"] = "done"
            job.stages["planner"] = "done"
            edl = json.loads(edl_path.read_text())
        else:
            hooks_path = session_dir / "hooks.json"
            while True:
                if resume and hooks_path.exists() and not job.more_hooks:
                    job.stages["hooks"] = "done"
                    hooks = json.loads(hooks_path.read_text())
                else:
                    with job.running("hooks"):
                        client = get_client(provider)
                        hooks = run_hooks(
                            session_dir,
                            candidates,
                            slots,
                            selection,
                            theme,
                            client,
                            model,
                        )
                job.hooks = hooks["lines"]
                first_line = hooks["lines"][0]["text"] if hooks["lines"] else ""
                preview_edl = run_planner(
                    session_dir,
                    manifest,
                    candidates,
                    slots,
                    selection,
                    selection_meta,
                    threads=THREADS,
                    config={"hook_line_override": first_line},
                )
                job.hook_slot = next(
                    c["slot"] for c in preview_edl["clips"] if c["role"] == "hook"
                )
                render_hook_previews(
                    preview_edl,
                    manifest,
                    session_dir,
                    [line["text"] for line in hooks["lines"]],
                    THREADS,
                    tonemap_chain,
                )

                job.pause_kind = "hook_choice"
                job.awaiting_confirmation = True
                job.confirm_event.wait()
                job.confirm_event.clear()
                job.awaiting_confirmation = False
                if job.cancelled:
                    return
                if not job.more_hooks:
                    break
                job.more_hooks = False

            with job.running("planner"):
                edl = run_planner(
                    session_dir,
                    manifest,
                    candidates,
                    slots,
                    selection,
                    selection_meta,
                    threads=THREADS,
                    config={
                        "hook_line_override": clean_hook_line(job.hook_choice),
                        "hook_text": bool(clean_hook_line(job.hook_choice)),
                    },
                )

        reel_path = session_dir / "reel.mp4"
        if resume and reel_path.exists():
            job.stages["render"] = "done"
        else:
            with job.running("render"):
                render_preview_segments(
                    edl,
                    manifest,
                    session_dir,
                    threads=THREADS,
                    tonemap_chain=tonemap_chain,
                )
                render_segments(
                    edl,
                    manifest,
                    session_dir,
                    threads=THREADS,
                    tonemap_chain=tonemap_chain,
                )
                concat_and_audio(edl, session_dir, threads=THREADS)

        with job.running("checks"):
            job.check_results = [str(r) for r in run_render_checks(edl, session_dir)]
    except Exception:  # noqa: BLE001 - surfaced to the status page, not swallowed
        job.error = traceback.format_exc()
    finally:
        job.done = True
