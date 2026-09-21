"""Regenerate `selector/known_confusions.txt` from labelled review
corrections, so the selector prompt's disambiguation cheat-sheet grows from
real mistakes instead of being hand-written every time a new confusion
pattern turns up (see the "Improve exercise detection" plan, Phase 2 item 3
follow-up).

Reads `var/exercise_openvocab_predictions.json` (what the selector guessed)
joined with `var/exercise_openvocab_verdicts.json` (thumbs-down + typed
correction, from `tools/validate_exercise_labels.py`), counts how often each
(wrong guess -> true exercise) pair recurs, and writes the pairs that recur
at least `--min-count` times as plain bullets `prompts.py` splices into
`SYSTEM_PROMPT_TEMPLATE` via `load_known_confusions()`.

Rerun after each labelling round:

    uv run python tools/refresh_confusion_rules.py
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PREDICTIONS_PATH = ROOT / "var" / "exercise_openvocab_predictions.json"
VERDICTS_PATH = ROOT / "var" / "exercise_openvocab_verdicts.json"
OUT_PATH = ROOT / "src" / "edl_agent" / "selector" / "known_confusions.txt"


def confusion_counts() -> Counter[tuple[str, str]]:
    """Counter of (wrong guess, true exercise) over every thumbs-down verdict
    with a typed correction, joined back to the prediction it corrects."""
    predictions = json.loads(PREDICTIONS_PATH.read_text()) if PREDICTIONS_PATH.exists() else {}
    verdicts = json.loads(VERDICTS_PATH.read_text()) if VERDICTS_PATH.exists() else {}
    counts: Counter[tuple[str, str]] = Counter()
    for session_id, session_verdicts in verdicts.items():
        session_predictions = predictions.get(session_id, {})
        for cand_id, v in session_verdicts.items():
            if v.get("verdict") != "down" or not v.get("correction"):
                continue
            pred = session_predictions.get(cand_id, {}).get("exercise")
            if not pred:
                continue
            counts[(pred, v["correction"])] += 1
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--min-count", type=int, default=2,
        help="Only pairs seen at least this many times become a rule (default: 2).",
    )
    args = parser.parse_args()

    counts = confusion_counts()
    pairs = sorted(
        ((pred, true, n) for (pred, true), n in counts.items() if n >= args.min_count),
        key=lambda p: -p[2],
    )
    if not pairs:
        OUT_PATH.write_text("")
        print(f"no pair seen >= {args.min_count} times, wrote empty {OUT_PATH}")
        return

    lines = [
        f'   - si dudas entre "{pred}" y "{true}", elige "{true}" salvo evidencia clara '
        f"en contra (confundidos {n}x en revisiones pasadas)."
        for pred, true, n in pairs
    ]
    OUT_PATH.write_text("\n".join(lines) + "\n")
    print(f"wrote {len(pairs)} confusion rule(s) to {OUT_PATH}")


if __name__ == "__main__":
    main()
