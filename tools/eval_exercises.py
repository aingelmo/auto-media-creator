"""Measure the open-vocabulary selector's exercise-labelling accuracy against
a fixed ground truth, across prompt changes -- what
`tools/validate_exercise_labels.py` alone can't do, since each `--predict`
rerun reselects candidates independently and a naive before/after diff is
mostly noise from *which* candidates got reselected, not label quality.

Ground truth is built from past review verdicts (no separate hand-labelling
pass): a thumbs-up means the prediction shown was correct, a thumbs-down with
a typed correction means the correction is correct. Per candidate this is a
frozen `{session_id: {candidate_id: true_exercise}}` map, independent of any
future selector run.

Each run reselects every ground-truthed session fresh and compares `exercise`
only for candidates that got reselected (`accuracy`), while also reporting
what fraction of ground truth that covers (`coverage`) -- a run that quietly
rejects more of the hard candidates must not look better on accuracy alone.

Usage:

    uv run python tools/eval_exercises.py --tag known-confusions-v1

Appends one `{tag, accuracy, coverage, confusions, ...}` entry per run to
`var/exercise_eval_runs.json` so runs are diffable over time.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PREDICTIONS_PATH = ROOT / "var" / "exercise_openvocab_predictions.json"
VERDICTS_PATH = ROOT / "var" / "exercise_openvocab_verdicts.json"
RUNS_PATH = ROOT / "var" / "exercise_eval_runs.json"

sys.path.insert(0, str(ROOT / "tools"))
from validate_exercise_labels import predict_session


def ground_truth() -> dict[str, dict[str, str]]:
    """`{session_id: {candidate_id: true_exercise}}` from past review verdicts."""
    predictions = json.loads(PREDICTIONS_PATH.read_text()) if PREDICTIONS_PATH.exists() else {}
    verdicts = json.loads(VERDICTS_PATH.read_text()) if VERDICTS_PATH.exists() else {}
    truth: dict[str, dict[str, str]] = {}
    for session_id, session_verdicts in verdicts.items():
        session_preds = predictions.get(session_id, {})
        for cand_id, v in session_verdicts.items():
            if v.get("verdict") == "up":
                pred = session_preds.get(cand_id, {}).get("exercise")
                if pred:
                    truth.setdefault(session_id, {})[cand_id] = pred
            elif v.get("verdict") == "down" and v.get("correction"):
                truth.setdefault(session_id, {})[cand_id] = v["correction"]
    return truth


def run_eval(tag: str) -> None:
    truth = ground_truth()
    if not truth:
        print("no reviewed verdicts yet -- run tools/validate_exercise_labels.py first")
        return

    correct = 0
    n_ground_truth = sum(len(c) for c in truth.values())
    confusions: Counter[tuple[str, str]] = Counter()
    for session_id, cand_truth in truth.items():
        print(f"predicting {session_id}...")
        preds = predict_session(session_id)
        for cand_id, true_exercise in cand_truth.items():
            pred = preds.get(cand_id, {}).get("exercise")
            if pred is None:
                continue  # not reselected this run -- excluded from accuracy, counted in coverage
            if pred == true_exercise:
                correct += 1
            else:
                confusions[(pred, true_exercise)] += 1

    n_covered = correct + sum(confusions.values())
    accuracy = correct / n_covered if n_covered else 0.0
    coverage = n_covered / n_ground_truth if n_ground_truth else 0.0

    print(
        f"\naccuracy: {correct}/{n_covered} = {accuracy:.1%}  "
        f"(coverage {n_covered}/{n_ground_truth} = {coverage:.1%})"
    )
    print("\ntop confusions:")
    for (pred, true), n in confusions.most_common(10):
        print(f"  {n}x  {pred!r} -> {true!r}")

    runs = json.loads(RUNS_PATH.read_text()) if RUNS_PATH.exists() else []
    runs.append(
        {
            "tag": tag,
            "timestamp": datetime.now(UTC).isoformat(),
            "accuracy": accuracy,
            "coverage": coverage,
            "n_correct": correct,
            "n_covered": n_covered,
            "n_ground_truth": n_ground_truth,
            "confusions": [
                {"pred": p, "true": t, "count": n} for (p, t), n in confusions.most_common()
            ],
        }
    )
    RUNS_PATH.write_text(json.dumps(runs, indent=2, ensure_ascii=False))
    print(f"\nappended to {RUNS_PATH}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tag", required=True, help="Label for this run, e.g. 'baseline' or 'known-confusions'."
    )
    args = parser.parse_args()
    run_eval(args.tag)


if __name__ == "__main__":
    main()
