"""One-off: regenerate hooks.json for every existing session, against the
current hook-copy system prompt (src/edl_agent/selector/hooks.py), so past
reels can be re-reviewed with tools/calibrate_prompts.py.

Backs up each session's old hooks.json before overwriting, to
hooks.json.bak (round 0, the pre-calibration original), then
hooks.json.bak.2, hooks.json.bak.3, ... on each later rerun -- every round
is kept, none clobbered, so rounds can be diffed N-way later.

    uv run python tools/rerun_hooks.py [session_id ...]
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from edl_agent.llm import get_client
from edl_agent.session import run_hooks
from edl_agent.web.pipeline import DEFAULT_MODELS

ROOT = Path(__file__).resolve().parent.parent
SESSIONS_DIR = ROOT / "var" / "sessions"
# candidates.json's peak_frames are stored relative to var/, e.g.
# "sessions/<id>/peaks/c01_0.jpg" -- match the app's own cwd expectation.
os.chdir(ROOT / "var")
MODEL_TO_PROVIDER = {v: k for k, v in DEFAULT_MODELS.items()}
THEME = "training"  # every session so far uses this theme, see hooks.py tone check


def rerun_one(session_dir: Path) -> None:
    hooks_path = session_dir / "hooks.json"
    if not hooks_path.exists():
        print(f"{session_dir.name}: skip, no hooks.json")
        return

    old_hooks = json.loads(hooks_path.read_text())
    backup_path = session_dir / "hooks.json.bak"
    n = 2
    while backup_path.exists():
        backup_path = session_dir / f"hooks.json.bak.{n}"
        n += 1
    backup_path.write_text(hooks_path.read_text())

    candidates = json.loads((session_dir / "candidates.json").read_text())
    selection_path = session_dir / "selection.json"
    selection = json.loads(selection_path.read_text()) if selection_path.exists() else None
    # base_edl (pre hook-text) if kept, else the final edl -- same clip
    # order/timings either way, only the hook text overlay differs.
    edl_path = session_dir / "edl_base.json"
    if not edl_path.exists():
        edl_path = session_dir / "edl.json"
    if not edl_path.exists():
        print(f"{session_dir.name}: skip, no edl.json (incomplete run)")
        return
    edl = json.loads(edl_path.read_text())

    selection_meta = json.loads((session_dir / "selection_meta.json").read_text())
    model = selection_meta.get("model", DEFAULT_MODELS["deepseek"])
    provider = MODEL_TO_PROVIDER.get(model, "deepseek")

    client = get_client(provider)
    new_hooks = run_hooks(
        session_dir,
        candidates,
        edl,
        selection,
        THEME,
        client,
        model,
        brief=old_hooks.get("brief", ""),
        audience=old_hooks.get("audience", "prospects"),
    )
    print(f"{session_dir.name}: {old_hooks.get('hook_line')!r} -> {new_hooks['hook_line']!r}")


def main() -> None:
    wanted = set(sys.argv[1:])
    dirs = sorted(SESSIONS_DIR.iterdir())
    if wanted:
        dirs = [d for d in dirs if d.name in wanted]
    for d in dirs:
        if d.is_dir():
            rerun_one(d)


if __name__ == "__main__":
    main()
