"""#5 wiring: session.run_selection computa duration_s y delega a selector.select."""
from __future__ import annotations

import sys
import types
from unittest.mock import patch

from edl_agent import session


def test_run_selection_computes_duration_s_and_builds_client(tmp_path, monkeypatch):
    fake_genai = types.ModuleType("google.genai")
    made_clients = []

    class _FakeClient:
        def __init__(self):
            made_clients.append(self)

    fake_genai.Client = _FakeClient
    fake_google = types.ModuleType("google")
    fake_google.genai = fake_genai
    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)

    slots_json = {"duration_f": 150, "slots": []}
    candidates_json = {"candidates": []}

    with patch.object(session, "selector_select", return_value=({"selected": []}, {"llm_attempts": 1})) as mock_select:
        selection, meta = session.run_selection(tmp_path, candidates_json, slots_json)

    assert selection == {"selected": []}
    assert meta == {"llm_attempts": 1}
    assert len(made_clients) == 1
    args, kwargs = mock_select.call_args
    assert args[0] is candidates_json
    assert args[1] is slots_json
    assert args[2] == 5.0  # 150 frames / 30 fps
    assert args[3] is made_clients[0]
    assert args[4] == tmp_path
