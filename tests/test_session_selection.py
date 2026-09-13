"""#5 wiring: session.run_selection computa duration_s y delega a selector.select."""

from __future__ import annotations

import sys
import types
from typing import Any, cast
from unittest.mock import patch

from edl_agent import session


def test_run_selection_computes_duration_s_and_builds_client(
    tmp_path, monkeypatch
) -> None:
    fake_genai = types.ModuleType("google.genai")
    made_clients = []

    class _FakeClient:
        def __init__(self) -> None:
            made_clients.append(self)

    cast("Any", fake_genai).Client = _FakeClient
    fake_google = types.ModuleType("google")
    cast("Any", fake_google).genai = fake_genai
    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)

    slots_json = {"duration_f": 150, "slots": []}
    candidates_json = {"candidates": []}

    with patch.object(
        session, "selector_select", return_value=({"selected": []}, {"llm_attempts": 1})
    ) as mock_select:
        selection, meta = session.run_selection(tmp_path, candidates_json, slots_json)

    assert selection == {"selected": []}
    assert meta == {"llm_attempts": 1}
    assert len(made_clients) == 1
    args, _kwargs = mock_select.call_args
    assert args[0] is candidates_json
    assert args[1] is slots_json
    assert args[2] == 5.0  # 150 frames / 30 fps
    assert args[3] is made_clients[0]
    assert args[4] == tmp_path


def _manifest(hdr="none"):
    return {
        "session_id": "s1",
        "sources": [
            {"type": "video", "hdr": hdr},
            {"type": "image"},  # non-video sources are ignored
        ],
    }


def test_tonemap_chain_for_manifest_hlg_and_dv84() -> None:
    from edl_agent.ingest import TONEMAP_CHAIN_HLG

    assert session.tonemap_chain_for_manifest(_manifest("hlg")) == TONEMAP_CHAIN_HLG
    assert session.tonemap_chain_for_manifest(_manifest("dv84")) == TONEMAP_CHAIN_HLG


def test_tonemap_chain_for_manifest_none_for_sdr() -> None:
    assert session.tonemap_chain_for_manifest(_manifest("none")) == ""


def test_run_planner_forwards_manifest_tonemap_chain_to_build_edl(
    tmp_path, monkeypatch
) -> None:
    from edl_agent.session import planner as planner_module

    manifest = _manifest("hlg")
    captured = {}

    def _fake_build_edl(**kwargs):
        captured.update(kwargs)
        return {"clips": []}

    monkeypatch.setattr(planner_module, "build_edl", _fake_build_edl)

    planner_module.run_planner(
        tmp_path,
        manifest,
        candidates_json={"candidates": []},
        slots_json={"slots": []},
    )

    assert captured["tonemap_chain"] == session.tonemap_chain_for_manifest(manifest)
    assert captured["tonemap_chain"] != ""
