"""edl_agent package.

Loads `.env` (repo root) into the environment on import, so API keys set
there are picked up without needing to export them in the shell. Existing
environment variables always win.
"""

from __future__ import annotations

import os
from pathlib import Path

_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

if _ENV_FILE.is_file():
    for _line in _ENV_FILE.read_text().splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _key, _, _value = _line.partition("=")
        os.environ.setdefault(_key.strip(), _value.strip().strip("'\""))
