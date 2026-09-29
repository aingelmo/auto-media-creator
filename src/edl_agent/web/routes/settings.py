"""Operator LLM API keys: status, save (persisted in the data volume), clear."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from edl_agent.keys import (
    PROVIDER_API_KEY_ENV,
    clear_api_key,
    keys_configured,
    store_api_key,
)

router = APIRouter()


class KeyBody(BaseModel):
    """Provider plus the key to persist (`""` is rejected with 400)."""

    provider: str = ""
    api_key: str = ""


@router.get("/api/settings/keys")
def get_keys() -> dict:
    """Per-provider key availability, never the secrets themselves.

    Returns:
        Mapping of provider to `{"configured": bool, "source": str}`
        (`"env"` | `"server"` | `"none"`); see `keys.keys_configured`.
    """
    return keys_configured()


@router.put("/api/settings/keys")
def put_key(body: KeyBody) -> dict:
    """Persist `body.api_key` for `body.provider` (`0600` in the volume).

    Returns:
        Dict with the `provider` and its fresh `configured`/`source`
        status (`"server"` on success).

    Raises:
        HTTPException: 400 for an unknown provider or a blank key.
    """
    if body.provider not in PROVIDER_API_KEY_ENV:
        raise HTTPException(
            status_code=400,
            detail=f"unknown provider {body.provider!r}",
        )
    if not body.api_key.strip():
        raise HTTPException(status_code=400, detail="API key must not be blank")
    try:
        store_api_key(body.provider, body.api_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"provider": body.provider, **keys_configured()[body.provider]}


@router.delete("/api/settings/keys/{provider}")
def delete_key(provider: str) -> dict:
    """Clear the persisted key for `provider` (env-provided keys are untouched).

    Returns:
        Dict with the `provider` and its fresh `configured`/`source`
        status (still `"env"`-configured when an env var provides it).

    Raises:
        HTTPException: 400 for an unknown provider.
    """
    if provider not in PROVIDER_API_KEY_ENV:
        raise HTTPException(status_code=400, detail=f"unknown provider {provider!r}")
    try:
        clear_api_key(provider)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"provider": provider, **keys_configured()[provider]}
