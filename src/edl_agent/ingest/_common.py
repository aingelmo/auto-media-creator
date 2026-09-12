"""Shared constants and errors, per #3."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

TARGET = {"w": 1080, "h": 1920, "fps": 30}


class IngestError(RuntimeError):
    """A source was rejected during ingestion (e.g. 10-bit without color_transfer)."""


def sha256_file(path: Path) -> str:
    """Compute the SHA-256 hash of a file's contents, read in 1 MiB chunks.

    Args:
        path: Path to the file to hash.

    Returns:
        SHA-256 hex digest of the file's contents.
    """
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
