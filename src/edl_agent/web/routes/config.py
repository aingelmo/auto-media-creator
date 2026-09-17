"""Config endpoint for the new-session/regenerate forms, plus the brand helper."""

from __future__ import annotations

import json
import shutil
from typing import TYPE_CHECKING

from fastapi import APIRouter, UploadFile

from edl_agent.web.pipeline import DEFAULT_MODELS
from edl_agent.web.state import UI_PROVIDERS

if TYPE_CHECKING:
    from pathlib import Path

router = APIRouter()


@router.get("/api/config")
def get_config() -> dict:
    """Providers/default-models for the new-session and regenerate forms."""
    return {"providers": UI_PROVIDERS, "default_models": DEFAULT_MODELS}


def save_brand(
    session_dir: Path, logo: UploadFile | None, handle: str, line: str
) -> None:
    """Write `brand/{logo.png,brand.json}` if a logo was uploaded; else leave as is.

    Per-session brand (#6.8): one business per session, nothing repo-level.
    """
    if logo is None or not logo.filename:
        return
    brand_dir = session_dir / "brand"
    brand_dir.mkdir(exist_ok=True)
    with (brand_dir / "logo.png").open("wb") as f:
        shutil.copyfileobj(logo.file, f)
    (brand_dir / "brand.json").write_text(
        json.dumps(
            {"logo": "brand/logo.png", "handle": handle.strip(), "line": line.strip()},
            ensure_ascii=False,
            indent=2,
        )
    )
