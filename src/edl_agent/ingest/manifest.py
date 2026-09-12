"""manifest.json assembly and I/O."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from ._common import TARGET

if TYPE_CHECKING:
    from pathlib import Path


def build_manifest(
    session_id: str, sources: list[dict], music: dict | None = None
) -> dict:
    """Assemble the manifest.json dict from already-probed sources.

    Args:
        session_id: Identifier of the session, copied into the manifest.
        sources: Per-source entries as built by `session.run_ingest` (each
            a dict with at least `src`, `sha256`, `type`, plus
            video-specific or image-specific fields).
        music: Music entry, or `None` if no music track was provided. Keys:
            `src`, `src_sha256`, `offset_s`, `max_duration_s`, `cut`,
            `cut_sha256`.

    Returns:
        Manifest dict with keys `session_id`, `target` (copy of `TARGET`),
        `sources`, and `music` (only present if `music` was given).
    """
    manifest = {
        "session_id": session_id,
        "target": dict(TARGET),
        "sources": sources,
    }
    if music is not None:
        manifest["music"] = music
    return manifest


def write_manifest(manifest: dict, path: Path) -> None:
    """Write manifest.json to `path`, creating the parent directory if missing.

    Args:
        manifest: Manifest dict, as returned by `build_manifest`.
        path: Output path for the JSON file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
