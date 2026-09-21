"""CPU/RAM profiler for a full no-cache EDL run. Mirrors scripts/run_e2e.py flow.

Usage: uv run scripts/profile_e2e.py <session_dir> <out_dir>
Writes samples.csv (0.2s polling of the whole process tree) + summary.json
(per-stage wall time, peak/mean RSS, peak/mean CPU). Both are always
written, even if a stage raises (partial results are marked as such).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import psutil

STAGE = {"name": "init"}
STOP = {"flag": False}
SAMPLES: list[dict] = []


def gpu_mem_mb() -> float:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=used_memory",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        vals = [float(x) for x in out.stdout.strip().split() if x.strip().isdigit()]
        return sum(vals)
    except Exception:
        return 0.0


def sampler(pid: int, interval: float = 0.2) -> None:
    me = psutil.Process(pid)
    me.cpu_percent(None)
    # Persistent handles per pid: a fresh Process object's first
    # cpu_percent() is 0.0, so prime new pids and read them next tick.
    # (Reading twice in one tick inflates CPU: ~0 wall-time delta.)
    procs: dict[int, psutil.Process] = {}
    tick = 0
    gpu = 0.0
    while not STOP["flag"]:
        tick += 1
        if tick % 10 == 0:
            gpu = gpu_mem_mb()
        try:
            live = [me, *me.children(recursive=True)]
        except psutil.NoSuchProcess:
            live = []
        seen: set[int] = set()
        rss = 0
        cpu = 0.0
        top = ""
        top_rss = 0
        for p in live:
            try:
                _pid = p.pid
                seen.add(_pid)
                h = procs.get(_pid)
                if h is None:
                    h = p
                    h.cpu_percent(None)  # prime; first real reading next tick
                    procs[_pid] = h
                else:
                    cpu += h.cpu_percent(None)
                r = h.memory_info().rss
                rss += r
                if r > top_rss:
                    top_rss = r
                    top = h.name()[:20]
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        for _pid in list(procs):
            if _pid not in seen:
                del procs[_pid]
        sys_cpu = psutil.cpu_percent(None)
        SAMPLES.append({
            "t": round(time.time(), 2),
            "stage": STAGE["name"],
            "total_rss_mb": round(rss / 1e6, 1),
            "cpu_pct": round(cpu, 1),
            "top_proc": top,
            "top_rss_mb": round(top_rss / 1e6, 1),
            "gpu_mem_mb": round(gpu, 1),
            "sys_cpu_pct": round(sys_cpu, 1),
        })
        time.sleep(interval)


def dump(outdir: Path, marks: dict[str, float], t0: float, partial: str) -> None:
    if not SAMPLES:
        print("no samples collected")
        return
    with (outdir / "samples.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(SAMPLES[0].keys()))
        w.writeheader()
        w.writerows(SAMPLES)
    stages = list(marks)
    end = marks.get("done", time.time())
    summary: dict = {
        "wall_s_total": round(end - t0, 1),
        "partial": partial,
        "stages": {},
    }
    for i, s in enumerate(stages):
        if s == "done":
            continue
        nxt = marks[stages[i + 1]] if i + 1 < len(stages) else end
        rows = [r for r in SAMPLES if r["stage"] == s]
        rss = [r["total_rss_mb"] for r in rows] or [0]
        cpu = [r["cpu_pct"] for r in rows] or [0]
        summary["stages"][s] = {
            "wall_s": round(nxt - marks[s], 1),
            "peak_rss_mb": round(max(rss), 1),
            "mean_rss_mb": round(sum(rss) / len(rss), 1),
            "peak_cpu_pct": round(max(cpu), 1),
            "mean_cpu_pct": round(sum(cpu) / len(cpu), 1),
            "peak_gpu_mb": max([r["gpu_mem_mb"] for r in rows] or [0]),
        }
    summary["peak_rss_mb"] = round(max(r["total_rss_mb"] for r in SAMPLES), 1)
    (outdir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", type=Path, help="Session dir with inputs/")
    parser.add_argument("outdir", type=Path, help="Where to write samples.csv")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument(
        "--no-preview", action="store_true", help="Skip the 540p preview render"
    )
    args = parser.parse_args()
    args.outdir.mkdir(parents=True, exist_ok=True)

    from edl_agent.features import free_torch_memory, yolo_pose_detector
    from edl_agent.llm import get_client
    from edl_agent.paths import MODELS_DIR
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

    session: Path = args.session
    threads: int = args.threads
    pose_model = str(MODELS_DIR / "yolov8n-pose.pt")
    provider, model, theme = "deepseek", "deepseek-flash", "training"

    t = threading.Thread(target=sampler, args=(os.getpid(),), daemon=True)
    t.start()
    marks: dict[str, float] = {}

    def mark(stage: str) -> None:
        STAGE["name"] = stage
        marks[stage] = time.time()

    t0 = time.time()
    try:
        mark("ingest")
        manifest = run_ingest(session, threads=threads, music_offset_s=15.0,
                              music_max_duration_s=15.0, cache_root=None)
        mark("slots")
        slots = slots_from_file(str(session / "music" / "track_cut.wav"))
        (session / "slots.json").write_text(json.dumps(slots, indent=2))
        mark("candidates")
        detector = yolo_pose_detector(pose_model)
        candidates = run_candidates(session, manifest, slots, detector,
                                    pose_model_path=pose_model, cache_root=None)
        # P0 light-device: torch holds ~3 GB resident after inference.
        del detector
        free_torch_memory()
        mark("selection")
        client = get_client(provider)
        selection, meta = run_selection(
            session, candidates, slots,
            config={"model": model, "theme": theme}, client=client)
        (session / "selection.json").write_text(json.dumps(selection or {}, indent=2))
        (session / "selection_meta.json").write_text(json.dumps(meta or {}, indent=2))
        mark("planner_base")
        base_edl = run_planner(session, manifest, candidates, slots, selection,
                               meta, threads=threads,
                               config={"hook_line_override": ""},
                               out_name="edl_base.json")
        mark("hooks")
        client = get_client(provider)
        hooks = run_hooks(session, candidates, base_edl, selection, theme,
                          client, model, hook_line_override="",
                          brief="", audience="prospects")
        mark("planner_final")
        edl = run_planner(session, manifest, candidates, slots, selection,
                          meta, threads=threads,
                          config={"hook_line_override": hooks["hook_line"]})
        mark("render_preview")
        if not args.no_preview:
            render_preview_segments(edl, manifest, session, threads=threads,
                                    tonemap_chain="")
        mark("render_segments")
        render_segments(edl, manifest, session, threads=threads, tonemap_chain="")
        mark("concat")
        concat_and_audio(edl, session, threads=threads)
        mark("checks")
        results = run_render_checks(edl, session)
        for r in results:
            print(r)
        marks["done"] = time.time()
        dump(args.outdir, marks, t0, "")
    except Exception as e:  # always dump partial data first
        print(f"STAGE-FAILED: {STAGE['name']}: {type(e).__name__}: {e}")
        dump(args.outdir, marks, t0, f"failed@{STAGE['name']}")
        raise
    finally:
        STOP["flag"] = True
        t.join(timeout=5)


if __name__ == "__main__":
    main()
