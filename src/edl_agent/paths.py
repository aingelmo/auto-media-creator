"""Runtime data directories, consolidated under a single `var/` root.

These are gitignored, machine-local directories (sessions, feature cache,
downloaded models) — distinct from `src/`, `docs/`, etc. which are checked
in. Override the root with `EDL_AGENT_VAR` (e.g. to point at a larger disk).
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VAR = Path(os.environ.get("EDL_AGENT_VAR", ROOT / "var"))
SESSIONS_DIR = VAR / "sessions"
CACHE_DIR = VAR / "cache"
MODELS_DIR = VAR / "models"
# Soft-delete bin: sessions and media moved aside instead of unlinked, so a
# mistaken delete is restorable for a retention window. See `web/trash.py`.
TRASH_DIR = VAR / "trash"
# Eval fixtures (test videos/songs/proxy cache) used by scripts/run_gap_eval_*.py.
DATA_DIR = VAR / "data"
