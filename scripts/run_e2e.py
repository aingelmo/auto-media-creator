"""Manual end-to-end driver for a session, per arquitectura_edl_agent_v4.md.
Not part of the library; ad-hoc script for real_test_02 validation.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from edl_agent.features import yolo_pose_detector
from edl_agent.ollama_client import OllamaClient
from edl_agent.render import (
    concat_and_audio,
    render_preview_segments,
    render_segments,
    run_render_checks,
)
from edl_agent.session import run_candidates, run_ingest, run_planner, run_selection
from edl_agent.slots import slots_from_file

SESSION = Path("sessions/real_test_02")
POSE_MODEL = "models/yolov8n-pose.pt"


def main() -> None:
    manifest = run_ingest(
        SESSION, threads=4, music_offset_s=15.0, music_max_duration_s=15.0
    )

    slots = slots_from_file(str(SESSION / "music" / "track_cut.wav"))
    (SESSION / "slots.json").write_text(json.dumps(slots, indent=2, ensure_ascii=False))

    detector = yolo_pose_detector(POSE_MODEL)
    candidates = run_candidates(
        SESSION, manifest, slots, detector, pose_model_path=POSE_MODEL
    )

    selection, selection_meta = run_selection(
        SESSION,
        candidates,
        slots,
        config={"model": "qwen3-vl:8b-instruct"},
        client=OllamaClient(),
    )
    0 if selection is None else len(selection["selected"])
    (SESSION / "selection.json").write_text(
        json.dumps(selection or {}, indent=2, ensure_ascii=False)
    )

    edl = run_planner(
        SESSION, manifest, candidates, slots, selection, selection_meta, threads=4
    )

    render_preview_segments(edl, manifest, SESSION, threads=4, tonemap_chain="")
    render_segments(edl, manifest, SESSION, threads=4, tonemap_chain="")
    concat_and_audio(edl, SESSION, threads=4)

    results = run_render_checks(edl, SESSION)
    for _r in results:
        pass


if __name__ == "__main__":
    main()
