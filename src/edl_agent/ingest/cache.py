"""Content-addressed cache of per-source ingest/features work across sessions.

Keyed by the source file's sha256, so a video reused across sessions (the
common case: sessions draw from a shared clip pool) skips `probe`+
`build_proxy`+`verify_source` (ingest) and `extract_features`+
`detect_scene_cuts` (candidates) on every run after the first. Sessions keep
their normal `proxies/`/`features/` layout; those paths become symlinks into
the cache (see `link_into`).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from typing import TYPE_CHECKING

from edl_agent.ingest.probe import VideoSourceInfo

if TYPE_CHECKING:
    from pathlib import Path


def tmp_path(path: Path) -> Path:
    """Per-process temp sibling of `path` (`<stem>.tmp.<pid><suffix>`).

    Write here, then `os.replace(tmp, path)`, so concurrent writers to the
    same cache entry never observe a torn/partial file (#last-writer-wins).
    Keeps `path`'s suffix at the end so format-sniffing writers (e.g.
    ffmpeg's muxer selection) still see the right extension.
    """
    return path.with_name(f"{path.stem}.tmp.{os.getpid()}{path.suffix}")


def atomic_write_text(path: Path, text: str) -> None:
    """Write `text` to `path` atomically via a temp file + `os.replace`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = tmp_path(path)
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def source_cache_dir(cache_root: Path, sha256: str) -> Path:
    """Return `cache_root/sha256`, creating it if missing."""
    d = cache_root / sha256
    d.mkdir(parents=True, exist_ok=True)
    return d


def cached_info(
    cache_root: Path, sha256: str, src: Path
) -> tuple[VideoSourceInfo, bool] | None:
    """Look up a previously cached `VideoSourceInfo`, per #1.

    Args:
        cache_root: Cache root directory (e.g. `data/cache`).
        sha256: Content hash of the source file.
        src: The source file's *current* path; re-stamped onto the
            returned `VideoSourceInfo.src` (the cache may have been
            populated from a differently-located copy of the same bytes).

    Returns:
        `(info, verified)` if `info.json` and `proxy.mp4` both exist in
        the cache entry, else `None`.
    """
    entry = cache_root / sha256
    info_path = entry / "info.json"
    if not info_path.exists() or not (entry / "proxy.mp4").exists():
        return None
    data = json.loads(info_path.read_text())
    verified = data.pop("proxy_verified")
    data["src"] = str(src)
    return VideoSourceInfo(**data), verified


def store_info(cache_root: Path, info: VideoSourceInfo, verified: bool) -> None:
    """Write `info.json` for `info.sha256`'s cache entry."""
    entry = source_cache_dir(cache_root, info.sha256)
    atomic_write_text(
        entry / "info.json",
        json.dumps({**asdict(info), "proxy_verified": verified}, ensure_ascii=False),
    )


def link_into(session_path: Path, cache_path: Path) -> None:
    """Symlink `session_path` to `cache_path`, replacing any existing file/link.

    Args:
        session_path: Path inside the session (e.g. `proxies/<stem>.mp4`);
            its parent directory is created if missing.
        cache_path: Target inside the cache; resolved to an absolute path
            so the symlink survives regardless of the session's location.
    """
    session_path.parent.mkdir(parents=True, exist_ok=True)
    if session_path.exists() or session_path.is_symlink():
        session_path.unlink()
    session_path.symlink_to(cache_path.resolve())
