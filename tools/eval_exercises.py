"""Standalone tool: measure the selector's exercise-labelling accuracy
against hand-labelled ground truth (see tools/label_exercises.py), so
prompt/frame changes to the exercise enum (#5.5) are validated instead of
judged by eye.

Re-runs the real selector call (edl_agent.selector.select) for each labelled
session -- same prompts, schema, frame extraction as production -- against a
scratch dir, so it never touches the real session's own selection.json.

    uv run python tools/eval_exercises.py --tag baseline [session_id ...]

Prints overall accuracy + coverage and the top confusion pairs, and appends
a `{tag, accuracy, coverage, confusions}` record to
var/exercise_eval_runs.json so runs are diffable across prompt changes.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SESSIONS_DIR = ROOT / "var" / "sessions"
GROUND_TRUTH_PATH = ROOT / "var" / "exercise_ground_truth.json"
RUNS_PATH = ROOT / "var" / "exercise_eval_runs.json"

sys.path.insert(0, str(ROOT / "src"))
# candidates.json's peak_frames are stored relative to var/, e.g.
# "sessions/<id>/peaks/c01_0.jpg" -- match the app's own cwd expectation
# (see tools/rerun_hooks.py, same idiom).
os.chdir(ROOT / "var")

from edl_agent.candidates._common import FPS  # noqa: E402
from edl_agent.llm import get_client  # noqa: E402
from edl_agent.selector import select  # noqa: E402
from edl_agent.web.pipeline import DEFAULT_MODELS  # noqa: E402

MODEL_TO_PROVIDER = {v: k for k, v in DEFAULT_MODELS.items()}
THEME = "training"  # every labelled session so far uses this theme


def eval_session(session_id: str, labels: dict[str, str]) -> dict:
    """Re-run the selector on one session and score its exercise labels.

    Returns `{session_id, correct, labeled_selected, total_labeled,
    confusions}`; `confusions` is a list of `(true, pred)` pairs for every
    mismatch. Skips (returns `total_labeled=0`) if the selector's own
    `selection` output is `None` (every attempt was "incomplete").
    """
    session_dir = SESSIONS_DIR / session_id
    candidates_json = json.loads((session_dir / "candidates.json").read_text())
    slots_json = json.loads((session_dir / "slots.json").read_text())
    duration_s = slots_json["duration_f"] / FPS

    selection_meta_path = session_dir / "selection_meta.json"
    model = DEFAULT_MODELS["gemini"]
    if selection_meta_path.exists():
        model = json.loads(selection_meta_path.read_text()).get("model", model)
    provider = MODEL_TO_PROVIDER.get(model, "gemini")
    client = get_client(provider)

    with tempfile.TemporaryDirectory() as scratch:
        selection, _meta = select(
            candidates_json,
            slots_json,
            duration_s,
            client,
            Path(scratch),
            config={"theme": THEME, "model": model},
        )

    if selection is None:
        return {
            "session_id": session_id,
            "correct": 0,
            "labeled_selected": 0,
            "total_labeled": len(labels),
            "confusions": [],
        }

    predicted = {e["candidate_id"]: e["exercise"] for e in selection["selected"]}
    correct = 0
    confusions: list[tuple[str, str]] = []
    labeled_selected = 0
    for cand_id, true_exercise in labels.items():
        pred = predicted.get(cand_id)
        if pred is None:
            continue  # selector rejected/didn't select this candidate
        labeled_selected += 1
        if pred == true_exercise:
            correct += 1
        else:
            confusions.append((true_exercise, pred))

    return {
        "session_id": session_id,
        "correct": correct,
        "labeled_selected": labeled_selected,
        "total_labeled": len(labels),
        "confusions": confusions,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session_ids", nargs="*", help="Restrict to these sessions.")
    parser.add_argument("--tag", default="run", help="Label for this run in the log.")
    args = parser.parse_args()

    ground_truth = json.loads(GROUND_TRUTH_PATH.read_text()) if GROUND_TRUTH_PATH.exists() else {}
    wanted = set(args.session_ids) or set(ground_truth)

    total_correct = 0
    total_labeled_selected = 0
    total_labeled = 0
    all_confusions: Counter[tuple[str, str]] = Counter()

    for session_id in sorted(wanted):
        labels = ground_truth.get(session_id, {}).get("candidates", {})
        if not labels:
            continue
        result = eval_session(session_id, labels)
        total_correct += result["correct"]
        total_labeled_selected += result["labeled_selected"]
        total_labeled += result["total_labeled"]
        all_confusions.update(result["confusions"])
        print(
            f"{session_id}: {result['correct']}/{result['labeled_selected']} correct "
            f"({result['total_labeled']} labeled)"
        )

    accuracy = total_correct / total_labeled_selected if total_labeled_selected else 0.0
    coverage = total_labeled_selected / total_labeled if total_labeled else 0.0
    print(f"\naccuracy: {accuracy:.1%} ({total_correct}/{total_labeled_selected})")
    print(f"coverage: {coverage:.1%} ({total_labeled_selected}/{total_labeled})")
    if all_confusions:
        print("\ntop confusions (true -> predicted):")
        for (true, pred), n in all_confusions.most_common(10):
            print(f"  {n:3d}  {true} -> {pred}")

    runs = json.loads(RUNS_PATH.read_text()) if RUNS_PATH.exists() else []
    runs.append(
        {
            "tag": args.tag,
            "ran_at": datetime.now(UTC).isoformat(),
            "accuracy": accuracy,
            "coverage": coverage,
            "confusions": [
                {"true": t, "pred": p, "n": n} for (t, p), n in all_confusions.most_common()
            ],
        }
    )
    RUNS_PATH.write_text(json.dumps(runs, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
