"""Resolve the ffmpeg/ffprobe binaries and check filter support.

Every pipeline stage shells out to `ffmpeg`/`ffprobe`, but bare names
resolve via the *server process's* `PATH`, which can differ from the
operator's shell (e.g. linuxbrew before `~/.local/bin`) and pick a
minimal build missing `zscale`/`drawtext`/`ass`. All callers must use
`ffmpeg_bin()`/`ffprobe_bin()` here instead of literals, and jobs
should call `require_filters()` up front so a bad binary fails fast
with an actionable message instead of `exit 8` mid-render. See
`docs/deployment.md` #2.
"""

from __future__ import annotations

import functools
import os
import shutil
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import collections.abc

# Full path to the ffmpeg binary, when `PATH` order can't be trusted
# (e.g. a brew-first login shell shadowing a full static build).
# `ffprobe` is resolved as its sibling when present, else via `PATH`.
FFMPEG_ENV_VAR = "EDL_AGENT_FFMPEG"


# Filters with no in-code fallback; `zscale` is deliberately absent
# (covered by `TONEMAP_CHAIN_HLG_BASIC`). Everything else the graphs use
# (`scale`, `overlay`, `crop`, …) ships in every build met so far.
REQUIRED_FILTERS = frozenset({"drawtext", "ass", "tonemap", "colorspace"})


class FFmpegError(RuntimeError):
    """The ffmpeg binary is missing or lacks required filters."""


@functools.lru_cache(maxsize=1)
def ffmpeg_bin() -> str:
    """Return the ffmpeg binary path for this process.

    Returns:
        `$EDL_AGENT_FFMPEG` when set, else `shutil.which("ffmpeg")`,
        else the bare `"ffmpeg"` (letting the spawn fail loudly).
    """
    return os.environ.get(FFMPEG_ENV_VAR) or shutil.which("ffmpeg") or "ffmpeg"


@functools.lru_cache(maxsize=1)
def ffprobe_bin() -> str:
    """Return the ffprobe binary path for this process.

    Returns:
        The `ffprobe` sibling of `$EDL_AGENT_FFMPEG` when that file
        exists, else `shutil.which("ffprobe")`, else bare `"ffprobe"`.
    """
    from pathlib import Path

    override = os.environ.get(FFMPEG_ENV_VAR)
    if override:
        sibling = Path(override).parent / "ffprobe"
        if sibling.is_file():
            return str(sibling)
    return shutil.which("ffprobe") or "ffprobe"


@functools.cache
def has_filter(name: str) -> bool:
    """Check whether this process's ffmpeg provides filter `name`.

    Args:
        name: Filter name, as listed by `ffmpeg -filters` (e.g.
            `"zscale"`, `"drawtext"`, `"ass"`).

    Returns:
        `True` if a `ffmpeg -filters` row names it, else `False`
        (including when ffmpeg itself can't be spawned).
    """
    try:
        proc = subprocess.run(
            [ffmpeg_bin(), "-hide_banner", "-filters"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return False
    return any(
        line.split()[1:2] == [name] for line in (proc.stdout or "").splitlines()
    )


def require_filters(names: collections.abc.Collection[str]) -> None:
    """Fail fast unless ffmpeg provides every filter in `names` (#2).

    Args:
        names: Required filter names (see `has_filter`).

    Raises:
        FFmpegError: If the binary can't be spawned or any filter is
            missing; the message names the binary, the missing
            filters, and `docs/deployment.md` #2.
    """
    missing = sorted(n for n in names if not has_filter(n))
    if missing:
        msg = (
            f"ffmpeg ({ffmpeg_bin()}) lacks required filters: "
            f"{', '.join(missing)} "
            "(see docs/deployment.md #2 for a full build)"
        )
        raise FFmpegError(msg)
