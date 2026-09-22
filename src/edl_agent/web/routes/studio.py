"""Studio API: timeline view plus develop/hook/effects edits."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from edl_agent.web import studio
from edl_agent.web.state import jobs

router = APIRouter()


class DevelopOrderBody(BaseModel):
    """Desired footage order across develop slots (a permutation)."""

    order: list[int]


class HookTextBody(BaseModel):
    """Manual hook text (`""` = no overlay)."""

    hook_text: str = ""


class EffectsBody(BaseModel):
    """Effects flags rebuilt deterministically into the EDL."""

    hook_flash: bool = False
    punch_in: bool = False


@router.get("/api/sessions/{name}/timeline")
def get_timeline(name: str) -> dict:
    """Studio timeline: EDL clips with locked flags and preview status."""
    try:
        return studio.timeline_payload(name)
    except HTTPException:
        raise
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/sessions/{name}/develop-order")
def post_develop_order(name: str, body: DevelopOrderBody) -> dict:
    """Permute footage across develop slots; hook/close stay fixed."""
    try:
        return studio.reorder_develops(name, body.order)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/sessions/{name}/hook-text")
def post_hook_text(name: str, body: HookTextBody) -> dict:
    """Set manual hook text and rebuild the EDL deterministically."""
    try:
        return studio.update_hook_text(name, body.hook_text, jobs.get(name))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/sessions/{name}/effects")
def post_effects(name: str, body: EffectsBody) -> dict:
    """Set effects flags and rebuild the EDL deterministically."""
    try:
        return studio.update_effects(
            name, body.hook_flash, body.punch_in, jobs.get(name)
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
