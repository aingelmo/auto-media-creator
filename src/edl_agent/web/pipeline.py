"""Background pipeline runner for the web UI, mirroring scripts/run_e2e.py."""

from __future__ import annotations

import json
import traceback
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from edl_agent.features import yolo_pose_detector
from edl_agent.llm import get_client
from edl_agent.render import (
    concat_and_audio,
    render_preview_segments,
    render_segments,
    run_render_checks,
)
from edl_agent.session import run_candidates, run_ingest, run_planner, run_selection
from edl_agent.slots import slots_from_file

if TYPE_CHECKING:
    from pathlib import Path

POSE_MODEL = "models/yolov8n-pose.pt"
THREADS = 4
MUSIC_OFFSET_S = 15.0
MUSIC_MAX_DURATION_S = 15.0
TONEMAP_CHAIN = ""

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
    "planner",
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
    """

    stages: dict[str, str] = field(
        default_factory=lambda: dict.fromkeys(STAGES, "pending")
    )
    error: str | None = None
    done: bool = False
    check_results: list[str] = field(default_factory=list)

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
    session_dir: Path, provider: str, model: str, job: JobState
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
    """
    try:
        with job.running("ingest"):
            manifest = run_ingest(
                session_dir,
                threads=THREADS,
                music_offset_s=MUSIC_OFFSET_S,
                music_max_duration_s=MUSIC_MAX_DURATION_S,
            )
            slots = slots_from_file(str(session_dir / "music" / "track_cut.wav"))
            slots_json = json.dumps(slots, indent=2, ensure_ascii=False)
            (session_dir / "slots.json").write_text(slots_json)

        with job.running("candidates"):
            detector = yolo_pose_detector(POSE_MODEL)
            candidates = run_candidates(
                session_dir, manifest, slots, detector, pose_model_path=POSE_MODEL
            )

        with job.running("selection"):
            client = get_client(provider)
            selection, selection_meta = run_selection(
                session_dir, candidates, slots, config={"model": model}, client=client
            )
            (session_dir / "selection.json").write_text(
                json.dumps(selection or {}, indent=2, ensure_ascii=False)
            )

        with job.running("planner"):
            edl = run_planner(
                session_dir,
                manifest,
                candidates,
                slots,
                selection,
                selection_meta,
                threads=THREADS,
            )

        with job.running("render"):
            render_preview_segments(
                edl,
                manifest,
                session_dir,
                threads=THREADS,
                tonemap_chain=TONEMAP_CHAIN,
            )
            render_segments(
                edl, manifest, session_dir, threads=THREADS, tonemap_chain=TONEMAP_CHAIN
            )
            concat_and_audio(edl, session_dir, threads=THREADS)

        with job.running("checks"):
            job.check_results = [str(r) for r in run_render_checks(edl, session_dir)]
    except Exception:  # noqa: BLE001 - surfaced to the status page, not swallowed
        job.error = traceback.format_exc()
    finally:
        job.done = True
