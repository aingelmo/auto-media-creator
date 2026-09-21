"""Manual end-to-end driver for a session, per docs/architecture/README.md.
Not part of the library; ad-hoc script for real_test_02 validation.

Usage: uv run scripts/run_e2e.py var/sessions/real_test_02 [--provider ollama]
    [--model qwen3-vl:8b-instruct]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from edl_agent.features import yolo_pose_detector
from edl_agent.llm import PROVIDERS, get_client
from edl_agent.paths import CACHE_DIR, MODELS_DIR
from edl_agent.render import (
    concat_and_audio,
    render_preview_segments,
    render_segments,
    run_render_checks,
)
from edl_agent.session import (
    run_candidates,
    run_hooks,
    run_ingest,
    run_planner,
    run_selection,
)
from edl_agent.slots import slots_from_file

POSE_MODEL = str(MODELS_DIR / "yolov8n-pose.pt")

DEFAULT_MODELS = {
    "gemini": "gemini-3.7-flash",
    "anthropic": "claude-sonnet-5",
    "deepseek": "deepseek-flash",
    "ollama": "qwen3-vl:8b-instruct",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "session", type=Path, help="Session directory, e.g. sessions/real_test_02"
    )
    parser.add_argument("--pose-model", default=POSE_MODEL)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--music-offset-s", type=float, default=15.0)
    parser.add_argument("--music-max-duration-s", type=float, default=15.0)
    parser.add_argument(
        "--provider", choices=PROVIDERS, default="ollama", help="Selector LLM provider"
    )
    parser.add_argument(
        "--model", default=None, help="Selector LLM model; defaults per --provider"
    )
    parser.add_argument(
        "--theme",
        choices=["training", "yoga"],
        default="training",
        help="Selector prompt theme",
    )
    parser.add_argument("--tonemap-chain", default="")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip stages whose output already exists on disk (e.g. after failure)",
    )
    parser.add_argument(
        "--hook-line",
        default="",
        help="Operator-typed hook text; skips the hook-copy LLM call",
    )
    parser.add_argument(
        "--brief",
        default="",
        help="Operator session brief (e.g. 'Hyrox class, Thursday, 12 people')",
    )
    parser.add_argument(
        "--audience",
        choices=["prospects", "members"],
        default="prospects",
        help="Hook copy tone: sell the class, or recognise the session",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=CACHE_DIR,
        help="Content-addressed cache dir for per-source ingest/features work",
    )
    parser.add_argument(
        "--no-cache", action="store_true", help="Disable the source cache"
    )
    args = parser.parse_args()
    if args.model is None:
        args.model = DEFAULT_MODELS[args.provider]
    return args


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def main() -> None:
    args = parse_args()
    session = args.session
    resume = args.resume

    cache_root = None if args.no_cache else args.cache_dir

    manifest_path = session / "manifest.json"
    if resume and manifest_path.exists():
        manifest = _load_json(manifest_path)
    else:
        manifest = run_ingest(
            session,
            threads=args.threads,
            music_offset_s=args.music_offset_s,
            music_max_duration_s=args.music_max_duration_s,
            cache_root=cache_root,
        )
        for warning in manifest.get("warnings", []):
            print(f"WARNING: {warning}")

    slots_path = session / "slots.json"
    if resume and slots_path.exists():
        slots = _load_json(slots_path)
    else:
        slots = slots_from_file(str(session / "music" / "track_cut.wav"))
        slots_path.write_text(json.dumps(slots, indent=2, ensure_ascii=False))

    candidates_path = session / "candidates.json"
    if resume and candidates_path.exists():
        candidates = _load_json(candidates_path)
    else:
        detector = yolo_pose_detector(args.pose_model)
        candidates = run_candidates(
            session,
            manifest,
            slots,
            detector,
            pose_model_path=args.pose_model,
            cache_root=cache_root,
        )

    selection_path = session / "selection.json"
    selection_meta_path = session / "selection_meta.json"
    if resume and selection_path.exists():
        selection = _load_json(selection_path) or None
        selection_meta = (
            _load_json(selection_meta_path) if selection_meta_path.exists() else {}
        )
    else:
        client = get_client(args.provider)
        selection, selection_meta = run_selection(
            session,
            candidates,
            slots,
            config={"model": args.model, "theme": args.theme},
            client=client,
        )
        selection_path.write_text(
            json.dumps(selection or {}, indent=2, ensure_ascii=False)
        )
        selection_meta_path.write_text(
            json.dumps(selection_meta or {}, indent=2, ensure_ascii=False)
        )

    edl_path = session / "edl.json"
    hooks_path = session / "hooks.json"
    if resume and edl_path.exists():
        edl = _load_json(edl_path)
    else:
        # Build the reel once with no hook text, so hook-copy generation
        # (#5.7) reads the final, ordered clip list -- what the viewer will
        # actually see -- instead of the selector's pre-planning pool.
        base_edl = run_planner(
            session,
            manifest,
            candidates,
            slots,
            selection,
            selection_meta,
            threads=args.threads,
            config={"hook_line_override": ""},
            out_name="edl_base.json",
        )
        if resume and hooks_path.exists():
            hooks = _load_json(hooks_path)
        else:
            client = get_client(args.provider)
            hooks = run_hooks(
                session,
                candidates,
                base_edl,
                selection,
                args.theme,
                client,
                args.model,
                hook_line_override=args.hook_line,
                brief=args.brief,
                audience=args.audience,
            )
        edl = run_planner(
            session,
            manifest,
            candidates,
            slots,
            selection,
            selection_meta,
            threads=args.threads,
            config={"hook_line_override": hooks["hook_line"]},
        )

    reel_path = session / "reel.mp4"
    if not (resume and reel_path.exists()):
        render_preview_segments(
            edl,
            manifest,
            session,
            threads=args.threads,
            tonemap_chain=args.tonemap_chain,
        )
        render_segments(
            edl,
            manifest,
            session,
            threads=args.threads,
            tonemap_chain=args.tonemap_chain,
        )
        concat_and_audio(edl, session, threads=args.threads)

    results = run_render_checks(edl, session)
    for r in results:
        print(r)


if __name__ == "__main__":
    main()
