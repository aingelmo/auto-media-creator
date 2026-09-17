"""Gap-evaluation batch: 15 random reels from data/test, run sequentially.

Builds each source video's proxy once into a shared cache (skipping the
per-session rebuild+reverify that sessions/_run_batch_reference.py.txt paid
15x over), then runs 15 sessions **one at a time as separate subprocesses**
(scripts/run_gap_eval_session.py) so each session's memory (YOLO, ollama
client, ffmpeg buffers) is fully released by the OS before the next session
starts — an in-process loop was observed to OOM around session 10.

Usage: uv run scripts/run_gap_eval_batch.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from edl_agent.ingest import TONEMAP_CHAIN_HLG, build_proxy, probe_video_source
from edl_agent.paths import DATA_DIR, SESSIONS_DIR
from edl_agent.verify import verify_source

VIDEOS = sorted(
    p for p in (DATA_DIR / "test/videos").glob("*")
    if p.suffix.lower() in {".mov", ".mp4"} and "Zone.Identifier" not in p.name
)
N_SESSIONS = 15
THREADS = 4

PROXY_CACHE_DIR = DATA_DIR / "test/proxy_cache"
CACHE_PROXIES = PROXY_CACHE_DIR / "proxies"
CACHE_INFO = PROXY_CACHE_DIR / "info.json"


def build_proxy_cache() -> None:
    """Probe+build+verify every source video's proxy once, per #3.2/#4.4.

    Reuses a prior cache (`data/test/proxy_cache/info.json`) for videos
    already verified there; only missing/unverified videos are (re)built.
    Videos that fail are logged and left `verified: false` (excluded from
    session sampling by `run_gap_eval_session.load_pool`).
    """
    CACHE_PROXIES.mkdir(parents=True, exist_ok=True)
    cached: dict[str, dict] = (
        json.loads(CACHE_INFO.read_text()) if CACHE_INFO.exists() else {}
    )

    for path in VIDEOS:
        d = cached.get(path.name)
        if d and d.get("verified") and (CACHE_PROXIES / f"{path.stem}.mp4").exists():
            continue
        print(f"proxy cache: building {path.name}", flush=True)
        try:
            info = probe_video_source(path)
            proxy_path = CACHE_PROXIES / f"{path.stem}.mp4"
            build_proxy(info, proxy_path, threads=THREADS)
            tonemap_chain = TONEMAP_CHAIN_HLG if info.hdr in ("hlg", "dv84") else ""
            verified, results = verify_source(
                original=str(path), proxy=str(proxy_path), tonemap_chain=tonemap_chain
            )
            cached[path.name] = {**asdict(info), "verified": verified}
            if not verified:
                msg = f"  FAILED verification: {[(r.t_s, r.distances) for r in results]}"
                print(msg)
        except Exception as e:
            print(f"  FAILED: {e}", flush=True)
            cached[path.name] = {"verified": False, "error": str(e)}

    CACHE_INFO.write_text(json.dumps(cached, indent=2, ensure_ascii=False))
    good = sum(1 for d in cached.values() if d.get("verified"))
    print(f"proxy cache: {good}/{len(VIDEOS)} videos usable")


def main() -> None:
    build_proxy_cache()

    results_log: list[dict[str, object]] = []
    for i in range(1, N_SESSIONS + 1):
        name = f"gap_eval_{i:02d}"
        print(f"=== {name} ===", flush=True)
        proc = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/run_gap_eval_session.py"),
                name,
                str(i),
            ],
            check=False,
        )
        result_path = SESSIONS_DIR / name / "_gap_eval_result.json"
        if proc.returncode == 0 and result_path.exists():
            results_log.append(json.loads(result_path.read_text()))
        else:
            result: dict[str, object] = {
                "name": name,
                "ok": False,
                "error": f"subprocess exit={proc.returncode}",
            }
            results_log.append(result)

    print("\n=== SUMMARY ===")
    for r in results_log:
        error_msg = r.get("error", "")  # type: ignore[attr-defined]
        error_str = str(error_msg)[:150] if error_msg else ""
        print(r["name"], "OK" if r.get("ok") else f"FAIL: {error_str}")

    (SESSIONS_DIR / "_gap_eval_report.json").write_text(
        json.dumps(results_log, indent=2, ensure_ascii=False)
    )


if __name__ == "__main__":
    main()
