"""Manual end-to-end driver for a session, per arquitectura_edl_agent_v4.md.
Not part of the library; ad-hoc script for real_test_02 validation.

Usage: uv run scripts/run_e2e.py sessions/real_test_02 [--model qwen3-vl:8b-instruct] [--gemini]
"""

from __future__ import annotations

import argparse
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

POSE_MODEL = "models/yolov8n-pose.pt"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", type=Path, help="Session directory, e.g. sessions/real_test_02")
    parser.add_argument("--pose-model", default=POSE_MODEL)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--music-offset-s", type=float, default=15.0)
    parser.add_argument("--music-max-duration-s", type=float, default=15.0)
    parser.add_argument("--model", default="qwen3-vl:8b-instruct", help="Selector LLM model")
    parser.add_argument(
        "--gemini",
        action="store_true",
        help="Use google.genai.Client() instead of local Ollama",
    )
    parser.add_argument("--tonemap-chain", default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    session = args.session

    manifest = run_ingest(
        session,
        threads=args.threads,
        music_offset_s=args.music_offset_s,
        music_max_duration_s=args.music_max_duration_s,
    )

    slots = slots_from_file(str(session / "music" / "track_cut.wav"))
    (session / "slots.json").write_text(json.dumps(slots, indent=2, ensure_ascii=False))

    detector = yolo_pose_detector(args.pose_model)
    candidates = run_candidates(
        session, manifest, slots, detector, pose_model_path=args.pose_model
    )

    client = None if args.gemini else OllamaClient()
    selection, selection_meta = run_selection(
        session,
        candidates,
        slots,
        config={"model": args.model},
        client=client,
    )
    (session / "selection.json").write_text(
        json.dumps(selection or {}, indent=2, ensure_ascii=False)
    )

    edl = run_planner(
        session, manifest, candidates, slots, selection, selection_meta, threads=args.threads
    )

    render_preview_segments(
        edl, manifest, session, threads=args.threads, tonemap_chain=args.tonemap_chain
    )
    render_segments(edl, manifest, session, threads=args.threads, tonemap_chain=args.tonemap_chain)
    concat_and_audio(edl, session, threads=args.threads)

    results = run_render_checks(edl, session)
    for r in results:
        print(r)


if __name__ == "__main__":
    main()
