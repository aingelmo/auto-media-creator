"""Deploy boot guarantees: vendor caches stay in the volume, data dirs exist.

Third-party ML libs default their caches to `$HOME` (ephemeral container
layer, lost on every recreate). `ensure_vendor_cache_env` pins the ones in
our dependency tree under `VAR/cache/vendor/` via `setdefault`, so explicit
operator env (e.g. compose) still wins. `ensure_runtime_dirs` creates the
volume subdirs and fails fast with the UID/`chown` hint when the bind mount
isn't writable, instead of dying mid-upload.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from edl_agent import paths

if TYPE_CHECKING:
    from pathlib import Path

# Env var -> subdirectory of `CACHE_DIR`. Only tools actually in the
# dependency tree: ultralytics writes `~/.config/Ultralytics` on first use,
# torch.hub defaults to `~/.cache/torch`. No HF/matplotlib deps exist, so
# no vars are pinned for them.
VENDOR_ENV_DEFAULTS = {
    "ULTRALYTICS_SETTINGS_DIR": "vendor/ultralytics",
    "TORCH_HOME": "vendor/torch",
}


def ensure_vendor_cache_env(root: Path | None = None) -> None:
    """Point vendor cache env vars at the volume (without overriding).

    Args:
        root: Data root; defaults to `paths.VAR` at call time so tests
            can pass a scratch dir.
    """
    var = root if root is not None else paths.VAR
    cache = var / "cache"
    for env_var, subpath in VENDOR_ENV_DEFAULTS.items():
        os.environ.setdefault(env_var, str(cache / subpath))


def ensure_runtime_dirs(root: Path | None = None) -> Path:
    """Create volume subdirs and probe writability, failing fast otherwise.

    Args:
        root: Data root; defaults to `paths.VAR` at call time so tests
            can pass a scratch dir.

    Returns:
        The data root in use.

    Raises:
        RuntimeError: If a subdirectory can't be created or a write
            probe fails (typically a host bind mount owned by another
            UID — the container runs as UID 1000).
    """
    var = root if root is not None else paths.VAR
    subdirs = [
        var / "sessions",
        var / "cache",
        var / "models",
        var / "trash",
        var / "config",
    ]
    try:
        for subdir in subdirs:
            subdir.mkdir(parents=True, exist_ok=True)
            probe = subdir / ".writetest"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
    except OSError as exc:
        msg = (
            f"data dir not writable: {exc} (EUID {os.geteuid()}). The "
            "EDL_AGENT_VAR bind mount must be writable by UID 1000, e.g. "
            "`chown -R 1000:1000 /host/path`."
        )
        raise RuntimeError(msg) from exc
    return var
