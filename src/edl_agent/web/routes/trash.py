"""Trash endpoints: list the soft-delete bin, restore, purge, empty."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from edl_agent.web import trash
from edl_agent.web.routes.media import restore_media_manifest

router = APIRouter()


@router.get("/api/trash")
def list_trash() -> dict:
    """List everything in the soft-delete bin, newest first.

    Reading the list also lazily purges items past their retention window.

    Returns:
        Dict with `items` (see `trash.list_items`) and `retention_days`
        (the restore window, for the SPA's copy).
    """
    return {"items": trash.list_items(), "retention_days": trash.PURGE_AFTER_DAYS}


@router.post("/api/trash/{item_id}/restore")
def restore_trash_item(item_id: str) -> dict:
    """Move one trashed session or media file back where it was.

    A restored media item also gets its `manifest.json` entry put back, so
    the session behaves as it did before the delete. Derived stage
    artifacts stay cleared and rebuild on the next run.

    Args:
        item_id: Trash item id from `GET /api/trash`.

    Returns:
        Dict with the restored `item`.

    Raises:
        HTTPException: 404 if the item is unknown or already purged; 409
            if something already occupies its original path.
    """
    try:
        item = trash.restore_item(item_id)
    except FileNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"no such trash item {item_id!r}"
        ) from None
    except FileExistsError:
        raise HTTPException(
            status_code=409,
            detail="the original location already exists; move or rename it first",
        ) from None
    if item.get("kind") == "media":
        restore_media_manifest(item)
    return {"item": item}


@router.delete("/api/trash/{item_id}")
def purge_trash_item(item_id: str) -> dict:
    """Permanently delete one trash item. This cannot be undone.

    Args:
        item_id: Trash item id from `GET /api/trash`.

    Returns:
        Dict with the purged `id`.

    Raises:
        HTTPException: 404 if the item is unknown or already purged.
    """
    try:
        trash.purge_item(item_id)
    except FileNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"no such trash item {item_id!r}"
        ) from None
    return {"id": item_id}


@router.delete("/api/trash")
def empty_trash() -> dict:
    """Permanently delete every trash item. This cannot be undone.

    Returns:
        Dict with `removed`, the number of items purged.
    """
    return {"removed": trash.empty()}
