"""Job progress tracking shared by all pipeline stages."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from edl_agent.paths import MODELS_DIR

if TYPE_CHECKING:
    from collections.abc import Iterator

POSE_MODEL = str(MODELS_DIR / "yolov8n-pose.pt")
THREADS = 4

STAGES = (
    "ingest",
    "candidates",
    "selection",
    "hooks",
    "planner",
    "render",
    "checks",
)

# UI-facing order: reel planning actually starts (and finishes) around hook
# generation, so display it before "hooks" even though STAGES (which drives
# regen artifact clearing) keeps "hooks" first for that index math.
DISPLAY_STAGES = (
    "ingest",
    "candidates",
    "selection",
    "planner",
    "hooks",
    "render",
    "checks",
)


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
            `"music_choice"`, `"verification"`, `"low_candidates"`,
            `"hook_choice"`, or `"effects_preview"`.
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
        hook_line_override: Operator-typed text from the regenerate-from-hooks
            form; if non-empty, `run_hooks` skips its LLM call entirely.
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
            beat, set via `/sessions/{name}/confirm` during an
            `"effects_preview"` pause; defaults to `False` so the effect is
            only enabled after the operator has watched a preview without
            it. Combined with `punch_in`, picks which cached
            `reel_preview{suffix}.mp4` (see `stages.render._combo_suffix`)
            the pause shows.
        punch_in: Whether develop clips get the punch-in zoom snap on cuts,
            set via `/sessions/{name}/confirm` during an `"effects_preview"`
            pause; defaults to `False` so the effect is only enabled after
            the operator has watched a preview without it.
        effects_preview_again: `True` (set via `/sessions/{name}/confirm`
            during an `"effects_preview"` pause) to rebuild the EDL with the
            new `hook_flash`/`punch_in` values and preview again, instead of
            proceeding to the full-resolution render.
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
    hook_flash: bool = False
    punch_in: bool = False
    effects_preview_again: bool = False
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
