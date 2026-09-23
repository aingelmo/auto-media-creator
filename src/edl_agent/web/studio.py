"""Studio edits: timeline view plus develop-only reorder, hook text, effects.

Single-studio flow keeps hook/close slots locked to the LLM pick while
develop slots are swappable. All three POSTs rebuild `edl.json`
deterministically (no LLM) and clear render artifacts so the next render
picks the change up.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from edl_agent.paths import SESSIONS_DIR
from edl_agent.selection.s_checks import clean_hook_line
from edl_agent.web.artifacts import clear_stage_artifacts
from edl_agent.web.jobs import JobState
from edl_agent.web.stages.planner import _build_final_edl
from edl_agent.web.state import jobs, load_json

if TYPE_CHECKING:
    from pathlib import Path

TIMING_KEYS = {"slot", "role", "timeline_start_f", "timeline_end_f", "n_frames"}


def timeline_payload(name: str) -> dict:
    """Return the studio timeline for a session.

    Args:
        name: Session directory name under `SESSIONS_DIR`.

    Returns:
        Dict with `clips` (each plus `locked`: `True` for hook/close,
        `False` for develop), `reel_exists`, `preview_exists`, and
        `preview_path` (`reel_preview{suffix}.mp4` if on disk), plus
        `prev_reel_exists` and `prev_reel_path` (`reel.prev.mp4` when a
        studio save or media delete invalidated the render; servable
        via `/sessions/{name}/files/reel.prev.mp4`).
    """
    edl = load_json(name, "edl.json")
    session_dir = SESSIONS_DIR / name
    clips = [
        {**clip, "locked": clip.get("role") in ("hook", "close")}
        for clip in edl.get("clips", [])
    ]
    reel_exists = (session_dir / "reel.mp4").exists()
    preview_path = ""
    for preview in sorted(session_dir.glob("reel_preview*.mp4")):
        preview_path = preview.name
    prev_reel_path = (
        "reel.prev.mp4"
        if (session_dir / "reel.prev.mp4").is_file()
        else ""
    )
    return {
        "clips": sorted(clips, key=lambda c: c["slot"]),
        "reel_exists": reel_exists,
        "preview_exists": bool(preview_path),
        "preview_path": preview_path,
        "prev_reel_exists": bool(prev_reel_path),
        "prev_reel_path": prev_reel_path,
    }


def _load_plan_inputs(session_dir: Path) -> tuple[dict, dict, dict, dict, dict]:
    """Load manifest/candidates/slots/selection/selection_meta from disk."""
    def _read(path: Path, default: dict) -> dict:
        if not path.exists():
            return default
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else default

    manifest = _read(session_dir / "manifest.json", {})
    candidates = _read(session_dir / "candidates.json", {})
    slots = _read(session_dir / "slots.json", {})
    selection = _read(session_dir / "selection.json", {})
    selection_meta = _read(session_dir / "selection_meta.json", {})
    return manifest, candidates, slots, selection, selection_meta


def reorder_develops(name: str, order: list[int]) -> dict:
    """Permute footage across develop slots, keeping slot timing fixed.

    Args:
        name: Session directory name.
        order: Develop slot numbers in desired footage order. Must be a
            permutation of the current develop slots; e.g. slots [1,2,3]
            with `order=[3,1,2]` puts slot-3's footage into slot-1.

    Returns:
        Fresh `timeline_payload(name)` after rewriting `edl.json`.

    Raises:
        ValueError: If `order` is not a permutation of develop slots, or
            no `edl.json` exists yet.
    """
    session_dir = SESSIONS_DIR / name
    edl_path = session_dir / "edl.json"
    if not edl_path.exists():
        msg = "edl.json not found yet"
        raise ValueError(msg)
    edl = json.loads(edl_path.read_text())
    develops = [c for c in edl.get("clips", []) if c.get("role") == "develop"]
    develop_slots = sorted(c["slot"] for c in develops)
    if sorted(order) != develop_slots:
        msg = f"order must permute develop slots {develop_slots}"
        raise ValueError(msg)
    by_slot = {c["slot"]: c for c in develops}
    ordered_footage = [
        {k: v for k, v in by_slot[s].items() if k not in TIMING_KEYS}
        for s in order
    ]
    for slot_clip, moving in zip(
        sorted(develops, key=lambda c: c["slot"]), ordered_footage, strict=True
    ):
        for key in list(slot_clip):
            if key not in TIMING_KEYS and key != "locked":
                del slot_clip[key]
        slot_clip.update(moving)
    edl_path.write_text(json.dumps(edl, indent=2, ensure_ascii=False))
    clear_stage_artifacts(session_dir, "render")
    job = jobs.get(name)
    if job is not None:
        job.stages["render"] = "pending"
        job.stages["checks"] = "pending"
    return timeline_payload(name)


def update_hook_text(name: str, hook_text: str, job: JobState | None) -> dict:
    """Set manual hook text and rebuild `edl.json` deterministically.

    Args:
        name: Session directory name.
        hook_text: Manual hook line (`""` = no text overlay).
        job: Live job to carry the choice, or `None` for a fresh state
            seeded from disk defaults.

    Returns:
        Fresh `timeline_payload(name)`.
    """
    session_dir = SESSIONS_DIR / name
    manifest, candidates, slots, selection, selection_meta = _load_plan_inputs(
        session_dir
    )
    active = job if job is not None else JobState()
    active.hook_choice = clean_hook_line(hook_text)
    _build_final_edl(
        session_dir, manifest, candidates, slots, selection or None,
        selection_meta, active,
    )
    if job is not None:
        job.hook_choice = active.hook_choice
    clear_stage_artifacts(session_dir, "render")
    if job is not None:
        job.stages["render"] = "pending"
        job.stages["checks"] = "pending"
    return timeline_payload(name)


def update_effects(
    name: str, hook_flash: bool, punch_in: bool, job: JobState | None
) -> dict:
    """Set effects flags and rebuild `edl.json` deterministically.

    Args:
        name: Session directory name.
        hook_flash: White flash on the hook peak beat.
        punch_in: Punch-in zoom snap on develop cuts.
        job: Live job to carry the flags, or `None` for disk defaults.

    Returns:
        Fresh `timeline_payload(name)`.
    """
    session_dir = SESSIONS_DIR / name
    manifest, candidates, slots, selection, selection_meta = _load_plan_inputs(
        session_dir
    )
    active = job if job is not None else JobState()
    active.hook_flash = hook_flash
    active.punch_in = punch_in
    if not (session_dir / "edl.json").exists():
        msg = "edl.json not found yet"
        raise ValueError(msg)
    current = json.loads((session_dir / "edl.json").read_text())
    clips_now = current.get("clips", [])
    hook_clip = next(
        (c for c in clips_now if c.get("role") == "hook"), {}
    )
    params = hook_clip.get("effect_params", {}) if isinstance(hook_clip, dict) else {}
    text = params.get("text", "") if isinstance(params, dict) else ""
    active.hook_choice = text if isinstance(text, str) else ""
    _build_final_edl(
        session_dir, manifest, candidates, slots, selection or None,
        selection_meta, active,
    )
    if job is not None:
        job.hook_flash = hook_flash
        job.punch_in = punch_in
    clear_stage_artifacts(session_dir, "render")
    if job is not None:
        job.stages["render"] = "pending"
        job.stages["checks"] = "pending"
    return timeline_payload(name)
