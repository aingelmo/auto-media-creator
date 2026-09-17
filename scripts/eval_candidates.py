"""Before/after yardstick for candidate-selection accuracy work.

Reads existing `var/sessions/*/candidates.json` + `selection.json` (no
re-render, no LLM calls) and reports per session: candidate counts by kind,
calm-per-clip, same-clip window redundancy, and LLM rejection reasons
bucketed by keyword.

Usage: uv run scripts/eval_candidates.py [session_dir ...]
    (defaults to every var/sessions/*/ with both files)
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from edl_agent.paths import SESSIONS_DIR

REDUNDANT_IOU = 0.8

REASON_BUCKETS = {
    "duplicate": r"duplicad|idéntic|similar|repet|redundan",
    "distance": r"lejan|pequeñ|lejos",
    "orientation": r"espalda|girad",
    "occlusion": r"tapad|cubiert|delante",
    "blur": r"desenfoc|borros",
}


def _window_iou(a: list[float], b: list[float]) -> float:
    lo, hi = max(a[0], b[0]), min(a[1], b[1])
    inter = max(0.0, hi - lo)
    union = min(a[1] - a[0], b[1] - b[0])
    return inter / union if union > 0 else 0.0


def _bucket(reason: str) -> str:
    for name, pattern in REASON_BUCKETS.items():
        if re.search(pattern, reason, re.IGNORECASE):
            return name
    return "other"


def eval_session(session_dir: Path) -> dict:
    """Compute the redundancy/calm/rejection metrics for one session.

    Args:
        session_dir: Session directory containing `candidates.json` and
            (optionally) `selection.json`.

    Returns:
        Dict with `name`, `n_candidates`, `by_kind` (Counter as dict),
        `calm_per_clip`, `redundant_pairs`/`total_pairs` (same-clip window
        IoU > `REDUNDANT_IOU`), and, if `selection.json` exists,
        `n_rejected`/`rejection_rate`/`rejection_buckets`.
    """
    candidates = json.loads((session_dir / "candidates.json").read_text())["candidates"]
    by_kind = Counter(c["kind"] for c in candidates)

    by_src: dict[str, list[dict]] = {}
    for c in candidates:
        by_src.setdefault(c["src"], []).append(c)

    redundant_pairs, total_pairs = 0, 0
    calm_clips = 0
    video_clips = 0
    for group in by_src.values():
        video = [c for c in group if c["kind"] != "image"]
        if not video:
            continue
        video_clips += 1
        if any(c["kind"] == "calm" for c in video):
            calm_clips += 1
        for a, b in combinations(video, 2):
            total_pairs += 1
            if _window_iou(a["window"], b["window"]) > REDUNDANT_IOU:
                redundant_pairs += 1

    result: dict = {
        "name": session_dir.name,
        "n_candidates": len(candidates),
        "by_kind": dict(by_kind),
        "calm_per_clip": round(calm_clips / video_clips, 2) if video_clips else 0.0,
        "redundant_pairs": redundant_pairs,
        "total_pairs": total_pairs,
    }

    selection_path = session_dir / "selection.json"
    if selection_path.exists():
        selection = json.loads(selection_path.read_text())
        rejected = selection.get("rejected", [])
        selected = selection.get("selected", [])
        buckets = Counter(_bucket(r.get("reason", "")) for r in rejected)
        total = len(selected) + len(rejected)
        result["n_rejected"] = len(rejected)
        result["rejection_rate"] = round(len(rejected) / total, 2) if total else 0.0
        result["rejection_buckets"] = dict(buckets)

    return result


def main() -> None:
    args = sys.argv[1:]
    if args:
        session_dirs = [Path(a) for a in args]
    else:
        session_dirs = sorted(
            d for d in SESSIONS_DIR.glob("*") if (d / "candidates.json").exists()
        )

    results = []
    for session_dir in session_dirs:
        try:
            results.append(eval_session(session_dir))
        except Exception as e:
            print(f"{session_dir.name}: FAILED ({e})")

    for r in results:
        print(f"== {r['name']} ==")
        print(f"  candidates: {r['n_candidates']} {r['by_kind']}")
        print(f"  calm/clip: {r['calm_per_clip']}")
        print(f"  redundant pairs: {r['redundant_pairs']}/{r['total_pairs']}")
        if "rejection_rate" in r:
            print(f"  LLM rejection rate: {r['rejection_rate']} {r['rejection_buckets']}")

    if results:
        n = len(results)
        print("== AGGREGATE ==")
        print(f"  avg candidates: {sum(r['n_candidates'] for r in results) / n:.1f}")
        print(f"  avg calm/clip: {sum(r['calm_per_clip'] for r in results) / n:.2f}")
        redund = sum(r["redundant_pairs"] for r in results)
        total = sum(r["total_pairs"] for r in results)
        print(f"  redundant pairs: {redund}/{total}")
        with_rej = [r for r in results if "rejection_rate" in r]
        if with_rej:
            avg_rej = sum(r["rejection_rate"] for r in with_rej) / len(with_rej)
            print(f"  avg LLM rejection rate: {avg_rej:.2f}")


if __name__ == "__main__":
    main()
