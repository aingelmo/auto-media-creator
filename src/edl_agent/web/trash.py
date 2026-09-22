"""Soft-delete bin: reversible removal of sessions and media (web console).

The console keeps one destructive grammar: deleting a session or a library
file moves its payload into `var/trash/<item-id>/payload/` and writes an
`item.json` record beside it, instead of unlinking it. `list_items` lazily
purges entries past `PURGE_AFTER_DAYS`, so a local single-process app needs
no scheduler; restore moves the payload back to the path it came from, and
purge is final.

An item id is `"<deleted_at_ms>-<kind>-<random>"`, which sorts by recency and
cannot collide when two deletes land in the same millisecond. Media records
keep the `session`/`relpath` they came from plus the manifest entries to
re-insert, so a restore is exact; sessions keep only their directory name.
"""

from __future__ import annotations

import json
import secrets
import shutil
import time
from typing import TYPE_CHECKING, Any

from edl_agent.paths import SESSIONS_DIR, TRASH_DIR

if TYPE_CHECKING:
    from pathlib import Path

# Restore window before a trashed item is permanently removed. Mirrored by
# the SPA's client-side preset bin (`frontend/src/trash.ts`).
PURGE_AFTER_DAYS = 30
_DAY_MS = 86_400_000


def _now_ms() -> int:
    """Current wall-clock time in unix milliseconds."""
    return int(time.time() * 1000)


def _item_dir(item_id: str) -> Path:
    """Resolve one item id to its trash directory, rejecting path escapes.

    Args:
        item_id: Item id as returned in trash records.

    Returns:
        `TRASH_DIR / item_id`.

    Raises:
        FileNotFoundError: If `item_id` is empty, starts with a dot, or
            contains a path separator or `..` — the route turns this into
            a 404 rather than ever reading outside `TRASH_DIR`.
    """
    if (
        not item_id
        or item_id.startswith(".")
        or "/" in item_id
        or "\\" in item_id
        or ".." in item_id
    ):
        raise FileNotFoundError(item_id)
    return TRASH_DIR / item_id


def _read_item(item_dir: Path) -> dict[str, Any] | None:
    """Read one trash item's `item.json`, or `None` when absent/corrupt."""
    try:
        item = json.loads((item_dir / "item.json").read_text())
    except (OSError, ValueError):
        return None
    return item if isinstance(item, dict) else None


def _write_item(item_dir: Path, item: dict[str, Any]) -> None:
    """Persist one trash item's `item.json`."""
    (item_dir / "item.json").write_text(
        json.dumps(item, indent=2, ensure_ascii=False)
    )


def _entry_size(path: Path) -> int:
    """Bytes to report for a payload about to be trashed.

    Args:
        path: File, symlink, or directory on its way into the bin.

    Returns:
        Total size in bytes. Directory trees are summed recursively;
        symlinks follow to their target (a picked media ref is a symlink
        to a shared copy, so the link's own size would be misleading);
        an unreadable entry contributes 0 rather than raising.
    """
    try:
        if path.is_dir() and not path.is_symlink():
            return sum(_entry_size(child) for child in path.iterdir())
        return path.stat().st_size
    except OSError:
        return 0


def _bin(
    *,
    kind: str,
    label: str,
    source: Path,
    session: str,
    origin: str,
    meta: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Move one payload into the bin and record its manifest.

    Args:
        kind: Trash kind, `"session"` or `"media"`.
        label: Human-facing name shown in the trash list.
        source: Absolute path to move (a session dir, a media file, or a
            media symlink). It must exist.
        session: Owning session name, for grouping and restore.
        origin: Session-relative path the payload came from, or the
            session directory name for a whole session.
        meta: Optional free-form details for the trash row (status, clip
            count, and similar), stored verbatim.
        extra: Optional extra top-level record keys (e.g. a media item's
            `relpath` and manifest entries).

    Returns:
        The stored trash item record.
    """
    TRASH_DIR.mkdir(parents=True, exist_ok=True)
    deleted_at = _now_ms()
    item_id = f"{deleted_at}-{kind}-{secrets.token_hex(3)}"
    item_dir = TRASH_DIR / item_id
    item_dir.mkdir()
    size_bytes = _entry_size(source)
    shutil.move(str(source), str(item_dir / "payload"))
    item: dict[str, Any] = {
        "id": item_id,
        "kind": kind,
        "label": label,
        "session": session,
        "origin": origin,
        "deleted_at": deleted_at,
        "purge_after": deleted_at + PURGE_AFTER_DAYS * _DAY_MS,
        "size_bytes": size_bytes,
        "meta": meta or {},
    }
    if extra:
        item.update(extra)
    _write_item(item_dir, item)
    return item


def trash_session(name: str, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """Move a whole session directory into the bin.

    Args:
        name: Session directory name under `SESSIONS_DIR`.
        meta: Optional summary details for the trash row.

    Returns:
        The stored trash item record.

    Raises:
        FileNotFoundError: If `SESSIONS_DIR / name` is not a directory.
    """
    session_dir = SESSIONS_DIR / name
    if not session_dir.is_dir():
        raise FileNotFoundError(name)
    return _bin(
        kind="session",
        label=name,
        source=session_dir,
        session=name,
        origin=name,
        meta=meta,
    )


def trash_media(
    session: str,
    relpath: str,
    *,
    source_entry: dict[str, Any] | None = None,
    music_entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Move one session-local media file (or symlink) into the bin.

    Args:
        session: Owning session directory name.
        relpath: Session-relative path, e.g. `"inputs/clip.mp4"`.
        source_entry: The `manifest["sources"]` entry removed for this
            file, kept so restore can re-insert it. `None` for music.
        music_entry: The `manifest["music"]` entry removed for this file,
            kept so restore can re-insert it. `None` for clips.

    Returns:
        The stored trash item record.

    Raises:
        FileNotFoundError: If the media path does not exist.
    """
    source = SESSIONS_DIR / session / relpath
    if not source.is_symlink() and not source.is_file():
        raise FileNotFoundError(relpath)
    return _bin(
        kind="media",
        label=source.name,
        source=source,
        session=session,
        origin=relpath,
        extra={
            "relpath": relpath,
            "source_entry": source_entry,
            "music_entry": music_entry,
        },
    )


def _restore_dest(item: dict[str, Any]) -> Path:
    """Absolute path a trash item's payload belongs at."""
    if item.get("kind") == "media":
        return SESSIONS_DIR / str(item["session"]) / str(item["relpath"])
    return SESSIONS_DIR / str(item["session"])


def list_items() -> list[dict[str, Any]]:
    """List trash items, newest first, purging anything past its window.

    Returns:
        One dict per item with `id`, `kind` (`"session"`/`"media"`),
        `label`, `session`, `origin`, `deleted_at` and `purge_after` (unix
        milliseconds), `size_bytes`, and `meta`.
    """
    _purge_expired()
    if not TRASH_DIR.is_dir():
        return []
    items = []
    for item_dir in TRASH_DIR.iterdir():
        item = _read_item(item_dir)
        if item is not None:
            items.append(item)
    items.sort(key=lambda i: int(i.get("deleted_at", 0)), reverse=True)
    return items


def restore_item(item_id: str) -> dict[str, Any]:
    """Move one trashed payload back to the path it came from.

    Args:
        item_id: Item id from `list_items`.

    Returns:
        The restored item record, so callers can resync derived state
        (e.g. re-insert a media entry into `manifest.json`).

    Raises:
        FileNotFoundError: If the item is unknown or already gone.
        FileExistsError: If something already occupies the destination,
            so a restore never overwrites a newer session or file.
    """
    item_dir = _item_dir(item_id)
    item = _read_item(item_dir)
    if item is None:
        raise FileNotFoundError(item_id)
    payload = item_dir / "payload"
    dest = _restore_dest(item)
    if dest.exists() or dest.is_symlink():
        raise FileExistsError(str(dest))
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(payload), str(dest))
    shutil.rmtree(item_dir, ignore_errors=True)
    return item


def purge_item(item_id: str) -> str:
    """Permanently remove one trash item and its payload.

    Args:
        item_id: Item id from `list_items`.

    Returns:
        The purged item id.

    Raises:
        FileNotFoundError: If the item is unknown or already gone.
    """
    item_dir = _item_dir(item_id)
    if not item_dir.is_dir():
        raise FileNotFoundError(item_id)
    shutil.rmtree(item_dir)
    return item_id


def empty() -> int:
    """Permanently remove every trash item.

    Returns:
        Number of items purged.
    """
    if not TRASH_DIR.is_dir():
        return 0
    removed = 0
    for item_dir in TRASH_DIR.iterdir():
        shutil.rmtree(item_dir, ignore_errors=True)
        removed += 1
    return removed


def _purge_expired() -> int:
    """Delete trash items whose retention window has passed.

    Returns:
        Number of items purged. Entries without a readable `item.json`
        are left alone: an orphan is not evidence that a user meant to
        delete whatever it contains.
    """
    if not TRASH_DIR.is_dir():
        return 0
    now = _now_ms()
    removed = 0
    for item_dir in TRASH_DIR.iterdir():
        item = _read_item(item_dir)
        if item is None:
            continue
        if int(item.get("purge_after", 0)) <= now:
            shutil.rmtree(item_dir, ignore_errors=True)
            removed += 1
    return removed
