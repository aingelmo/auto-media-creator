"""Real end-to-end smoke test for the low-candidates confirmation pause.

Builds a fresh session from just 2 real clips (deliberately too few for the
slots the music produces) plus a real music track, runs the actual web
pipeline (real ffmpeg proxies, real YOLO pose detection, real Ollama
selection call) in a background thread, and drives the confirmation pause
the way the web UI's "Shorten"/"Keep" buttons would.

Requires a local Ollama with the selector model pulled (see
DEFAULT_MODEL below) and var/models/yolov8n-pose.pt present.

Usage: uv run scripts/smoke_low_candidates_pause.py [--keep]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from edl_agent.paths import SESSIONS_DIR
from edl_agent.session._common import MUSIC_EXTS
from edl_agent.web.pipeline import JobState, run_pipeline_job

DEFAULT_MODEL = "qwen3-vl:8b-instruct"
DEFAULT_CLIPS = ["IMG_1056.MOV", "IMG_8105.mov"]  # known to yield real candidates


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    default_src = SESSIONS_DIR / "deepseek_test_06"
    parser.add_argument("--src-session", type=Path, default=default_src)
    default_out = SESSIONS_DIR / "low_candidates_smoke"
    parser.add_argument("--out", type=Path, default=default_out)
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Choose 'keep current duration' at the pause instead of 'shorten'",
    )
    parser.add_argument("--clips", nargs="+", default=DEFAULT_CLIPS)
    return parser.parse_args()


def build_session(src_session: Path, out: Path, clip_names: list[str]) -> None:
    if out.exists():
        shutil.rmtree(out)
    (out / "inputs").mkdir(parents=True)
    (out / "music").mkdir()

    for name in clip_names:
        shutil.copy(src_session / "inputs" / name, out / "inputs" / name)
    print(f"using {len(clip_names)} clip(s): {clip_names}")

    track = next(
        p
        for p in (src_session / "music").iterdir()
        if p.suffix.lower() in MUSIC_EXTS
    )
    shutil.copy(track, out / "music" / track.name)


def main() -> None:
    args = parse_args()
    build_session(args.src_session, args.out, args.clips)

    job = JobState()
    thread = threading.Thread(
        target=run_pipeline_job,
        args=(args.out, "ollama", DEFAULT_MODEL, job),
    )
    thread.start()

    deadline = time.monotonic() + 600
    while (
        not job.awaiting_confirmation
        and not job.done
        and time.monotonic() < deadline
    ):
        time.sleep(1)

    if not job.awaiting_confirmation:
        thread.join(timeout=600)
        print("job.error:", job.error)
        print("never paused; done =", job.done)
        sys.exit(1 if job.error or not job.done else 0)

    print("paused:", job.pause_kind)
    if job.pause_kind == "low_candidates":
        print("low_candidates:", job.low_candidates)
        assert job.low_candidates["real_sources"] < job.low_candidates["slot_count"]
        job.shorten = not args.keep
    else:
        print("unverified_sources:", job.unverified_sources)
    job.cancelled = False
    job.confirm_event.set()

    thread.join(timeout=600)
    print("done:", job.done, "error:", job.error)

    slots = json.loads((args.out / "slots.json").read_text())
    print(f"final slot count: {len(slots['slots'])}, duration_f: {slots['duration_f']}")
    assert (args.out / "reel.mp4").exists()
    print("reel.mp4 rendered OK")


if __name__ == "__main__":
    main()
