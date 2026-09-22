"""Studio edits: develop-only reorder, hook text, effects rebuild."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from edl_agent.web import studio


def _write_edl(session_dir, clips) -> None:
    (session_dir / "edl.json").write_text(json.dumps({"clips": clips}))


def _clip(slot, role, candidate):
    return {
        "slot": slot,
        "role": role,
        "candidate_id": candidate,
        "src": f"inputs/{candidate}.mov",
        "in_s": float(slot),
        "out_s": float(slot) + 1.0,
        "timeline_start_f": slot * 30,
        "timeline_end_f": slot * 30 + 30,
        "n_frames": 30,
    }


def _patch_dirs(monkeypatch, tmp_path):
    import edl_agent.paths as paths_mod
    import edl_agent.web.state as state_mod
    import edl_agent.web.studio as studio_mod

    monkeypatch.setattr(paths_mod, "SESSIONS_DIR", tmp_path)
    monkeypatch.setattr(state_mod, "SESSIONS_DIR", tmp_path)
    monkeypatch.setattr(studio_mod, "SESSIONS_DIR", tmp_path)
    monkeypatch.setattr(studio_mod, "jobs", {})


def test_timeline_flags_hook_close_locked(tmp_path, monkeypatch) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    session_dir = tmp_path / "s1"
    session_dir.mkdir()
    _write_edl(
        session_dir,
        [
            _clip(0, "hook", "a"),
            _clip(1, "develop", "b"),
            _clip(2, "close", "c"),
        ],
    )
    payload = studio.timeline_payload("s1")
    locked = {c["slot"]: c["locked"] for c in payload["clips"]}
    assert locked == {0: True, 1: False, 2: True}


def test_reorder_develops_permutes_footage_keeps_timing(
    tmp_path, monkeypatch
) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    session_dir = tmp_path / "s1"
    session_dir.mkdir()
    _write_edl(
        session_dir,
        [
            _clip(0, "hook", "a"),
            _clip(1, "develop", "b"),
            _clip(2, "develop", "c"),
            _clip(3, "close", "d"),
        ],
    )
    payload = studio.reorder_develops("s1", [2, 1])
    by_slot = {c["slot"]: c for c in payload["clips"]}
    assert by_slot[1]["candidate_id"] == "c"
    assert by_slot[2]["candidate_id"] == "b"
    assert by_slot[1]["timeline_start_f"] == 30
    assert by_slot[0]["candidate_id"] == "a"
    assert by_slot[3]["candidate_id"] == "d"


def test_reorder_rejects_non_develop_slots(tmp_path, monkeypatch) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    session_dir = tmp_path / "s1"
    session_dir.mkdir()
    _write_edl(session_dir, [_clip(0, "hook", "a"), _clip(1, "develop", "b")])
    with pytest.raises(ValueError, match="permute develop slots"):
        studio.reorder_develops("s1", [0, 1])


def test_update_hook_text_rebuilds_edl(tmp_path, monkeypatch) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    import edl_agent.web.studio as studio_mod
    session_dir = tmp_path / "s1"
    session_dir.mkdir()
    for name in ("manifest.json", "candidates.json", "slots.json"):
        (session_dir / name).write_text("{}")
    (session_dir / "selection.json").write_text("{}")
    (session_dir / "selection_meta.json").write_text("{}")
    _write_edl(session_dir, [_clip(0, "hook", "a")])
    seen = {}

    def fake_build(session_dir, manifest, candidates, slots, selection, meta, job):
        seen["hook"] = job.hook_choice
        edl = {"clips": [_clip(0, "hook", "a")]}
        (session_dir / "edl.json").write_text(json.dumps(edl))
        return edl

    with patch.object(studio_mod, "_build_final_edl", side_effect=fake_build):
        studio.update_hook_text("s1", "mi linea", None)
    assert seen["hook"] == "mi linea"


def test_update_effects_rebuilds_edl(tmp_path, monkeypatch) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    import edl_agent.web.studio as studio_mod
    session_dir = tmp_path / "s1"
    session_dir.mkdir()
    for name in ("manifest.json", "candidates.json", "slots.json"):
        (session_dir / name).write_text("{}")
    (session_dir / "selection.json").write_text("{}")
    (session_dir / "selection_meta.json").write_text("{}")
    _write_edl(session_dir, [_clip(0, "hook", "a")])
    seen = {}

    def fake_build(session_dir, manifest, candidates, slots, selection, meta, job):
        seen["flash"] = job.hook_flash
        seen["punch"] = job.punch_in
        edl = {"clips": [_clip(0, "hook", "a")]}
        (session_dir / "edl.json").write_text(json.dumps(edl))
        return edl

    with patch.object(studio_mod, "_build_final_edl", side_effect=fake_build):
        studio.update_effects("s1", True, True, None)
    assert seen == {"flash": True, "punch": True}
