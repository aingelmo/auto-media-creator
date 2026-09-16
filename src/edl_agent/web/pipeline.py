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
from edl_agent.ingest import (
    cut_music,
    ffprobe,
    rank_highlights,
    sha256_file,
    write_manifest,
)
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
    DEFAULT_CACHE_DIR,
    run_candidates,
    run_hooks,
    run_ingest,
    run_planner,
    run_selection,
    tonemap_chain_for_manifest,
)
from edl_agent.session._common import MUSIC_EXTS
from edl_agent.slots import slots_from_file

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

POSE_MODEL = "models/yolov8n-pose.pt"
THREADS = 4
MUSIC_OFFSET_S = 15.0
MUSIC_MAX_DURATION_S = 15.0
MIN_SHORTEN_DURATION_S = 5.0
SHORTEN_ATTEMPTS = 4  # beat detection isn't linear in duration; try progressively
MUSIC_CANDIDATE_COUNT = 3


def _shorten_durations(start_s: float) -> list[float]:
    """Decreasing durations to try when shortening, from `start_s` down to minimum.

    Beat detection doesn't scale slot count linearly with duration, so a
    single guessed duration isn't reliable; each step is retried against the
    real slot count until one produces few enough slots (see the
    `"low_candidates"` pause in `run_pipeline_job`).
    """
    if start_s <= MIN_SHORTEN_DURATION_S:
        return [MIN_SHORTEN_DURATION_S]
    step = (start_s - MIN_SHORTEN_DURATION_S) / (SHORTEN_ATTEMPTS - 1)
    return [round(start_s - i * step, 1) for i in range(SHORTEN_ATTEMPTS)]


def _find_music_track(session_dir: Path) -> Path | None:
    """Return the session's music track file, if any."""
    music_dir = session_dir / "music"
    if not music_dir.is_dir():
        return None
    return next(
        (p for p in sorted(music_dir.iterdir()) if p.suffix.lower() in MUSIC_EXTS),
        None,
    )


def _probe_duration_s(path: Path) -> float:
    """Return a media file's duration in seconds, via ffprobe."""
    return float(ffprobe(path)["format"]["duration"])


def _generate_music_candidates(
    track: Path,
    out_dir: Path,
    session_dir: Path,
    already: int,
    duration_s: float,
    cache_root: Path | None,
    count: int = MUSIC_CANDIDATE_COUNT,
) -> list[dict]:
    """Cut the next `count` ranked candidate snippets, after `already` picked ones.

    Ranks every `window_s` offset in `track` by drop-detection heuristic
    (see `rank_highlights`), snapped to the nearest downbeat, and cuts ranks
    `[already, already + count)`. Falls back to evenly-spaced offsets if
    ranking fails or runs out.

    Returns:
        New candidate dicts (`{"offset_s", "path", "score"}`, `path`
        relative to `session_dir`), appended after `already` existing ones.
    """
    usable = duration_s - MUSIC_MAX_DURATION_S
    try:
        ranked = rank_highlights(
            track, MUSIC_MAX_DURATION_S, cache_root=cache_root
        )
    except Exception:  # noqa: BLE001 (any librosa/decode failure -> fallback)
        ranked = []
    batch = ranked[already : already + count]
    if len(batch) < count:
        step = usable / max(count, 1)
        batch += [
            {"offset_s": round(step * i, 1), "score": None}
            for i in range(already + len(batch), already + count)
        ]

    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for i, cand in enumerate(batch):
        idx = already + i
        path = out_dir / f"cand_{idx}.wav"
        cut_music(track, path, cand["offset_s"], MUSIC_MAX_DURATION_S)
        results.append(
            {
                "offset_s": cand["offset_s"],
                "path": str(path.relative_to(session_dir)),
                "score": cand.get("score"),
            }
        )
    return results


def _run_music_choice_pause(
    session_dir: Path, job: JobState, track: Path, cache_root: Path | None
) -> float:
    """Pause for the operator to pick a music offset, per the `"music_choice"` pause.

    Generates batches of `MUSIC_CANDIDATE_COUNT` ranked candidate cuts (best
    first), accumulating them in `job.music_candidates` across "generate
    more" rounds so earlier batches stay pickable.

    Returns:
        The chosen offset, in seconds.

    Raises:
        _JobCancelledError: If the operator declines the pause.
    """
    duration_s = _probe_duration_s(track)
    if duration_s <= MUSIC_MAX_DURATION_S:
        return 0.0

    candidates_dir = session_dir / "music" / "candidates"
    job.music_candidates = []
    while True:
        new = _generate_music_candidates(
            track,
            candidates_dir,
            session_dir,
            len(job.music_candidates),
            duration_s,
            cache_root,
        )
        job.music_candidates += new

        job.pause_kind = "music_choice"
        job.awaiting_confirmation = True
        job.confirm_event.wait()
        job.confirm_event.clear()
        job.awaiting_confirmation = False
        if job.cancelled:
            raise _JobCancelledError
        if not job.more_music:
            return job.music_choice_offset
        job.more_music = False


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
    "planner": ["edl.json", "edl_b.json"],
    "render": [
        "reel.mp4",
        "segments",
        "preview_segments",
        "reel_b.mp4",
        "segments_b",
        "preview_segments_b",
    ],
    "checks": [],
}


def clear_stage_artifacts(session_dir: Path, from_stage: str) -> None:
    """Delete `from_stage` and later stages' output so resume=True redoes them.

    Backs up an existing `reel.mp4` to `reel.prev.mp4` before deleting it.

    Args:
        session_dir: Session directory to clear artifacts in.
        from_stage: First stage (in `STAGES` order) to force a redo of.
    """
    reel_path = session_dir / "reel.mp4"
    if reel_path.exists():
        shutil.copy(reel_path, session_dir / "reel.prev.mp4")
    reel_b_path = session_dir / "reel_b.mp4"
    if reel_b_path.exists():
        shutil.copy(reel_b_path, session_dir / "reel_b.prev.mp4")

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
            `"music_choice"`, `"verification"`, `"low_candidates"`, or
            `"hook_choice"`.
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
        hook_line_override: Operator-typed text from the new-session form;
            if non-empty, `run_hooks` skips its LLM call entirely.
        brief: Operator-typed session brief from the new-session form,
            passed to `run_hooks` to ground the `contexto` angle.
        audience: `"prospects"` | `"members"`, from the new-session form,
            passed to `run_hooks` to set the copy's tone.
        hooks: Latest `hooks.json` dict (`hook_line`, `hooks`, `dropped`,
            `evidence`, `rejected`, `source`), for the hook-choice template.
        hook_slot: Slot number of the hook clip, so the template can build
            preview URLs (`hook_previews/{key}/seg_{hook_slot:02d}.mp4`).
        hook_choice: Chosen/custom hook text (`""` = no text), set via
            `/sessions/{name}/confirm` during a `"hook_choice"` pause.
        hook_choice_b: Chosen hook text for variant B (`""` = no variant
            B), set via `/sessions/{name}/confirm` during a `"hook_choice"`
            pause (idea #7).
        hook_flash: Whether the hook clip gets its white flash on the peak
            beat, set via `/sessions/{name}/confirm` during a
            `"hook_choice"` pause; defaults to `True`.
        more_hooks: `True` (set via `/sessions/{name}/confirm`) to
            generate a fresh batch of 3 lines instead of proceeding to the
            final render.
        check_results_b: Stringified `run_render_checks` results for
            variant B, once the `checks` stage completes with a B variant.
        detail: Human-readable sub-step text for whichever stage is
            currently `"running"` (e.g. "calling deepseek for hook line"),
            cleared back to `""` each time a stage starts or finishes.
        music_candidates: Candidate music cuts (`{"offset_s", "path", "score"}`)
            accumulated so far during a `"music_choice"` pause; grows across
            "generate more" rounds instead of being replaced.
        music_choice_offset: Operator-picked offset (seconds), set via
            `/sessions/{name}/confirm` during a `"music_choice"` pause.
        more_music: `True` (set via `/sessions/{name}/confirm`) to generate
            another batch of candidate cuts instead of proceeding with the
            picked offset.
    """

    stages: dict[str, str] = field(
        default_factory=lambda: dict.fromkeys(STAGES, "pending")
    )
    detail: dict[str, str] = field(default_factory=lambda: dict.fromkeys(STAGES, ""))
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
    hook_line_override: str = ""
    brief: str = ""
    audience: str = "prospects"
    hooks: dict = field(default_factory=dict)
    hook_slot: int = 0
    hook_choice: str = ""
    hook_choice_b: str = ""
    hook_flash: bool = True
    more_hooks: bool = False
    check_results_b: list[str] = field(default_factory=list)
    music_candidates: list[dict] = field(default_factory=list)
    music_choice_offset: float = 0.0
    more_music: bool = False

    @contextmanager
    def running(self, stage: str) -> Iterator[None]:
        """Mark `stage` `"running"`, then `"done"`, or `"failed"` on exception."""
        self.stages[stage] = "running"
        self.detail[stage] = ""
        try:
            yield
        except Exception:
            self.stages[stage] = "failed"
            raise
        else:
            self.stages[stage] = "done"
            self.detail[stage] = ""


class _JobCancelledError(Exception):
    """Internal signal: the operator declined to proceed past a confirmation pause."""


def _run_ingest_stage(
    session_dir: Path, job: JobState, resume: bool
) -> tuple[dict, dict]:
    """Run (or resume) the ingest stage, pausing if any proxy is unverified.

    Returns:
        `(manifest, slots)`.

    Raises:
        _JobCancelledError: If the operator declines the verification pause.
    """
    manifest_path = session_dir / "manifest.json"
    slots_path = session_dir / "slots.json"
    if resume and manifest_path.exists() and slots_path.exists():
        job.stages["ingest"] = "done"
        return json.loads(manifest_path.read_text()), json.loads(
            slots_path.read_text()
        )

    track = _find_music_track(session_dir)
    music_offset_s = MUSIC_OFFSET_S
    if track is not None:
        music_offset_s = _run_music_choice_pause(
            session_dir, job, track, DEFAULT_CACHE_DIR
        )

    with job.running("ingest"):
        job.detail["ingest"] = "probing sources, building proxies"
        manifest = run_ingest(
            session_dir,
            threads=THREADS,
            music_offset_s=music_offset_s,
            music_max_duration_s=MUSIC_MAX_DURATION_S,
            cache_root=DEFAULT_CACHE_DIR,
        )
        job.detail["ingest"] = "cutting music, detecting beat slots"
        slots = slots_from_file(str(session_dir / "music" / "track_cut.wav"))
        slots_path.write_text(json.dumps(slots, indent=2, ensure_ascii=False))

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
            raise _JobCancelledError
        if job.excluded_sources:
            manifest["sources"] = [
                s for s in manifest["sources"] if s["src"] not in job.excluded_sources
            ]
            write_manifest(manifest, session_dir / "manifest.json")
    return manifest, slots


def _run_candidates_stage(
    session_dir: Path, job: JobState, resume: bool, manifest: dict, slots: dict
) -> tuple[dict, dict]:
    """Run (or resume) the candidates stage, pausing if usable sources are scarce.

    Re-cuts the music to a shorter duration and rebuilds `slots` if the
    operator chooses to shorten past a `"low_candidates"` pause.

    Returns:
        `(candidates, slots)` -- `slots` may differ from the input if shortened.

    Raises:
        _JobCancelledError: If the operator declines the low-candidates pause.
    """
    candidates_path = session_dir / "candidates.json"
    if resume and candidates_path.exists():
        job.stages["candidates"] = "done"
        return json.loads(candidates_path.read_text()), slots

    with job.running("candidates"):
        job.detail["candidates"] = "loading pose model"
        detector = yolo_pose_detector(POSE_MODEL)
        job.detail["candidates"] = "extracting features, detecting candidates"
        candidates = run_candidates(
            session_dir,
            manifest,
            slots,
            detector,
            pose_model_path=POSE_MODEL,
            cache_root=DEFAULT_CACHE_DIR,
        )

    real_sources = len(
        {
            c["src"]
            for c in candidates["candidates"]
            if c["kind"] != "image" and c["admits_slots"]
        }
    )
    slot_count = len(slots["slots"])
    has_video_sources = any(s.get("type") == "video" for s in manifest["sources"])
    if not (has_video_sources and real_sources < slot_count):
        return candidates, slots

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
        raise _JobCancelledError
    if not job.shorten:
        return candidates, slots

    music = manifest["music"]
    cut_path = session_dir / "music" / "track_cut.wav"
    orig_track = session_dir / music["src"]

    best_duration, best_slots = None, None
    for new_duration in _shorten_durations(job.low_candidates["suggested_duration_s"]):
        cut_music(orig_track, cut_path, music["offset_s"], new_duration)
        candidate_slots = slots_from_file(str(cut_path))
        if best_slots is None or len(candidate_slots["slots"]) < len(
            best_slots["slots"]
        ):
            best_duration, best_slots = new_duration, candidate_slots
        if len(candidate_slots["slots"]) <= real_sources:
            break

    if best_slots is None or best_duration is None:
        msg = "No valid slot duration found"
        raise RuntimeError(msg)

    if new_duration != best_duration:
        cut_music(orig_track, cut_path, music["offset_s"], best_duration)
    slots = best_slots

    music["max_duration_s"] = best_duration
    music["cut_sha256"] = sha256_file(cut_path)
    write_manifest(manifest, session_dir / "manifest.json")

    (session_dir / "slots.json").write_text(
        json.dumps(slots, indent=2, ensure_ascii=False)
    )
    readmit_candidates(candidates["candidates"], slots["slots"])
    candidates_path.write_text(json.dumps(candidates, indent=2, ensure_ascii=False))

    return candidates, slots


def _run_selection_stage(
    session_dir: Path,
    job: JobState,
    resume: bool,
    candidates: dict,
    slots: dict,
    provider: str,
    model: str,
    theme: str,
) -> tuple[dict | None, dict]:
    """Run (or resume) the selection stage.

    Returns:
        `(selection, selection_meta)`.
    """
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
        return selection, selection_meta

    with job.running("selection"):
        job.detail["selection"] = f"calling {provider} for clip selection"
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
    return selection, selection_meta


def _run_hooks_and_planner_stage(
    session_dir: Path,
    job: JobState,
    resume: bool,
    provider: str,
    model: str,
    theme: str,
    manifest: dict,
    candidates: dict,
    slots: dict,
    selection: dict | None,
    selection_meta: dict,
    tonemap_chain: str,
) -> dict:
    """Run (or resume) the hooks stage (looping on retries), then the planner stage.

    Returns:
        Final `edl` dict.

    Raises:
        _JobCancelledError: If the operator declines the hook-choice pause.
    """
    edl_path = session_dir / "edl.json"
    if resume and edl_path.exists():
        job.stages["hooks"] = "done"
        job.stages["planner"] = "done"
        return json.loads(edl_path.read_text())

    hooks_path = session_dir / "hooks.json"
    while True:
        if resume and hooks_path.exists() and not job.more_hooks:
            job.stages["hooks"] = "done"
            hooks = json.loads(hooks_path.read_text())
        else:
            with job.running("hooks"):
                job.detail["hooks"] = f"calling {provider} for hook line"
                client = get_client(provider)
                hooks = run_hooks(
                    session_dir,
                    candidates,
                    slots,
                    selection,
                    theme,
                    client,
                    model,
                    hook_line_override=job.hook_line_override,
                    brief=job.brief,
                    audience=job.audience,
                )
        job.hooks = hooks
        job.detail["hooks"] = "building preview EDL"
        preview_edl = run_planner(
            session_dir,
            manifest,
            candidates,
            slots,
            selection,
            selection_meta,
            threads=THREADS,
            config={"hook_line_override": hooks["hook_line"]},
        )
        job.hook_slot = next(
            c["slot"] for c in preview_edl["clips"] if c["role"] == "hook"
        )
        job.detail["hooks"] = "rendering hook line previews"
        render_hook_previews(
            preview_edl,
            manifest,
            session_dir,
            [h["hook_line"] for h in hooks["hooks"] if h["hook_line"]],
            THREADS,
            tonemap_chain,
        )
        job.detail["hooks"] = ""

        job.pause_kind = "hook_choice"
        job.awaiting_confirmation = True
        job.confirm_event.wait()
        job.confirm_event.clear()
        job.awaiting_confirmation = False
        if job.cancelled:
            raise _JobCancelledError
        if not job.more_hooks:
            break
        job.more_hooks = False

    with job.running("planner"):
        job.detail["planner"] = "building final EDL"
        return run_planner(
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
                "hook_flash": job.hook_flash,
            },
        )


def _run_render_stage(
    session_dir: Path,
    job: JobState,
    resume: bool,
    edl: dict,
    manifest: dict,
    tonemap_chain: str,
) -> None:
    """Run (or resume) the render stage, then always run the render checks."""
    reel_path = session_dir / "reel.mp4"
    if resume and reel_path.exists():
        job.stages["render"] = "done"
    else:
        with job.running("render"):
            job.detail["render"] = "rendering preview segments (0/0)"
            render_preview_segments(
                edl,
                manifest,
                session_dir,
                threads=THREADS,
                tonemap_chain=tonemap_chain,
                on_progress=lambda done, total: job.detail.__setitem__(
                    "render", f"rendering preview segments ({done}/{total})"
                ),
            )
            job.detail["render"] = "rendering final segments (0/0)"
            render_segments(
                edl,
                manifest,
                session_dir,
                threads=THREADS,
                tonemap_chain=tonemap_chain,
                on_progress=lambda done, total: job.detail.__setitem__(
                    "render", f"rendering final segments ({done}/{total})"
                ),
            )
            job.detail["render"] = "concatenating segments, mixing audio"
            concat_and_audio(edl, session_dir, threads=THREADS)

    with job.running("checks"):
        job.detail["checks"] = "verifying rendered reel"
        job.check_results = [str(r) for r in run_render_checks(edl, session_dir)]


def _run_variant_b_stage(
    session_dir: Path,
    job: JobState,
    manifest: dict,
    candidates: dict,
    slots: dict,
    selection: dict | None,
    selection_meta: dict,
    edl: dict,
    tonemap_chain: str,
) -> None:
    """Render, mix, and check hook variant B (idea #7), if the operator chose one.

    Reuses A's segment files for every clip whose dict is identical in B
    (only the hook slot differs), so B costs one segment render.
    """
    hook_line_b = clean_hook_line(job.hook_choice_b)
    if not hook_line_b:
        return

    with job.running("render"):
        job.detail["render"] = "building variant B EDL"
        edl_b = run_planner(
            session_dir,
            manifest,
            candidates,
            slots,
            selection,
            selection_meta,
            threads=THREADS,
            config={
                "hook_line_override": hook_line_b,
                "hook_text": True,
                "peak_beat_index": 2,
                "hook_flash": job.hook_flash,
            },
            out_name="edl_b.json",
        )
        clips_b_by_slot = {c["slot"]: c for c in edl_b["clips"]}
        reuse_final = {
            c["slot"]: session_dir / "segments" / f"seg_{c['slot']:02d}.mp4"
            for c in edl["clips"]
            if c == clips_b_by_slot.get(c["slot"])
        }
        reuse_preview = {
            c["slot"]: session_dir / "preview_segments" / f"seg_{c['slot']:02d}.mp4"
            for c in edl["clips"]
            if c == clips_b_by_slot.get(c["slot"])
        }
        job.detail["render"] = "rendering variant B preview segments"
        render_preview_segments(
            edl_b,
            manifest,
            session_dir,
            threads=THREADS,
            tonemap_chain=tonemap_chain,
            suffix="_b",
            reuse=reuse_preview,
        )
        job.detail["render"] = "rendering variant B final segments"
        render_segments(
            edl_b,
            manifest,
            session_dir,
            threads=THREADS,
            tonemap_chain=tonemap_chain,
            suffix="_b",
            reuse=reuse_final,
        )
        job.detail["render"] = "concatenating variant B, mixing audio"
        concat_and_audio(edl_b, session_dir, threads=THREADS, suffix="_b")

    with job.running("checks"):
        job.detail["checks"] = "verifying variant B reel"
        job.check_results_b = [
            str(r) for r in run_render_checks(edl_b, session_dir, suffix="_b")
        ]


def run_pipeline_job(
    session_dir: Path,
    provider: str,
    model: str,
    job: JobState,
    resume: bool = False,
    theme: str = "training",
    hook_line_override: str = "",
    brief: str = "",
    audience: str = "prospects",
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
        hook_line_override: Operator-typed hook text from the new-session
            form; if non-empty, the `hooks` stage skips its LLM call.
        brief: Operator-typed session brief from the new-session form.
        audience: `"prospects"` | `"members"`, from the new-session form.
    """
    job.provider = provider
    job.model = model
    job.theme = theme
    job.hook_line_override = hook_line_override
    job.brief = brief
    job.audience = audience
    try:
        manifest, slots = _run_ingest_stage(session_dir, job, resume)
        candidates, slots = _run_candidates_stage(
            session_dir, job, resume, manifest, slots
        )
        selection, selection_meta = _run_selection_stage(
            session_dir, job, resume, candidates, slots, provider, model, theme
        )
        tonemap_chain = tonemap_chain_for_manifest(manifest)
        edl = _run_hooks_and_planner_stage(
            session_dir,
            job,
            resume,
            provider,
            model,
            theme,
            manifest,
            candidates,
            slots,
            selection,
            selection_meta,
            tonemap_chain,
        )
        _run_render_stage(session_dir, job, resume, edl, manifest, tonemap_chain)
        _run_variant_b_stage(
            session_dir,
            job,
            manifest,
            candidates,
            slots,
            selection,
            selection_meta,
            edl,
            tonemap_chain,
        )
    except _JobCancelledError:
        pass
    except Exception:  # noqa: BLE001 - surfaced to the status page, not swallowed
        job.error = traceback.format_exc()
    finally:
        job.done = True
