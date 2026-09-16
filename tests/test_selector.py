"""#5 Selector LLM: peticion inline-image, schema y reintentos por incomplete."""

from __future__ import annotations

import json

import requests

from edl_agent.selector import admissible_candidates, build_parts, select
from edl_agent.selector.hooks import generate_hook_copy, hook_copy_schema
from edl_agent.selector.prompts import build_system_prompt, build_user_prompt


def _cand(cid, admits, peak_frame):
    return {
        "id": cid,
        "src": "a.mov",
        "kind": "peak",
        "multi_subject": False,
        "admits_slots": admits,
        "peak_frames": [str(peak_frame)],
    }


def _slots_json():
    return {
        "duration_f": 150,
        "slots": [
            {"slot": 0, "role": "hook"},
            {"slot": 1, "role": "develop"},
            {"slot": 2, "role": "close"},
        ],
    }


class _FakeUsage:
    def model_dump(self):
        return {
            "total_input_tokens": 1000,
            "total_output_tokens": 200,
            "total_thought_tokens": 300,
        }


class _FakeInteraction:
    def __init__(self, status, output_text=None, usage=None) -> None:
        self.status = status
        self.output_text = output_text
        self.usage = usage or _FakeUsage()


class _FakeInteractions:
    def __init__(self, responses) -> None:
        self._responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class _FakeClient:
    def __init__(self, responses) -> None:
        self.interactions = _FakeInteractions(responses)


def _selection_payload():
    return {
        "selected": [
            {
                "candidate_id": "c1",
                "role": "hook",
                "rank": 1,
                "exercise": "back squat",
                "reason": "explosive",
            }
        ],
        "rejected": [],
        "notes": "",
    }


def test_admissible_candidates_filters_by_slot() -> None:
    candidates_json = {
        "candidates": [_cand("c1", [0], "f.jpg"), _cand("c2", [5], "f.jpg")]
    }
    out = admissible_candidates(candidates_json, _slots_json())
    assert [c["id"] for c in out] == ["c1"]


def test_build_parts_embeds_id_line_and_base64_image(tmp_path) -> None:
    jpg = tmp_path / "f.jpg"
    jpg.write_bytes(b"fake-jpeg-bytes")
    parts = build_parts([_cand("c1", [0], jpg)], "USER_PROMPT")
    assert parts[0] == {
        "type": "text",
        "text": "id=c1 kind=peak src=a.mov multi_subject=False velocidad=0.00",
    }
    assert parts[1]["type"] == "image"
    assert parts[1]["resolution"] == "low"
    assert parts[-1] == {"type": "text", "text": "USER_PROMPT"}


def test_select_returns_selection_on_first_complete_attempt(tmp_path) -> None:
    jpg = tmp_path / "f.jpg"
    jpg.write_bytes(b"x")
    candidates_json = {"candidates": [_cand("c1", [0], jpg)]}
    client = _FakeClient(
        [_FakeInteraction("completed", json.dumps(_selection_payload()))]
    )

    selection, meta = select(
        candidates_json,
        _slots_json(),
        duration_s=20.0,
        client=client,
        session_dir=tmp_path,
    )

    assert selection == _selection_payload()
    assert meta["llm_attempts"] == 1
    assert meta["llm_cost_usd"] > 0
    assert (tmp_path / "selection_attempt_1.json").exists()
    assert not (tmp_path / "selection_attempt_2.json").exists()


def test_select_retries_once_on_incomplete_then_succeeds(tmp_path) -> None:
    jpg = tmp_path / "f.jpg"
    jpg.write_bytes(b"x")
    candidates_json = {"candidates": [_cand("c1", [0], jpg)]}
    client = _FakeClient(
        [
            _FakeInteraction("incomplete"),
            _FakeInteraction("completed", json.dumps(_selection_payload())),
        ]
    )

    selection, meta = select(
        candidates_json,
        _slots_json(),
        duration_s=20.0,
        client=client,
        session_dir=tmp_path,
    )

    assert selection == _selection_payload()
    assert meta["llm_attempts"] == 2
    assert (tmp_path / "selection_attempt_1.json").exists()
    assert (tmp_path / "selection_attempt_2.json").exists()
    assert "8 palabras" in client.interactions.calls[1]["system_instruction"]


def test_select_returns_none_after_max_attempts_incomplete(tmp_path) -> None:
    jpg = tmp_path / "f.jpg"
    jpg.write_bytes(b"x")
    candidates_json = {"candidates": [_cand("c1", [0], jpg)]}
    client = _FakeClient(
        [_FakeInteraction("incomplete"), _FakeInteraction("incomplete")]
    )

    selection, meta = select(
        candidates_json,
        _slots_json(),
        duration_s=20.0,
        client=client,
        session_dir=tmp_path,
    )

    assert selection is None
    assert meta["llm_attempts"] == 2


def test_select_recovers_from_transient_read_timeout(tmp_path) -> None:
    jpg = tmp_path / "f.jpg"
    jpg.write_bytes(b"x")
    candidates_json = {"candidates": [_cand("c1", [0], jpg)]}
    client = _FakeClient(
        [
            requests.exceptions.ReadTimeout("upstream timed out"),
            _FakeInteraction("completed", json.dumps(_selection_payload())),
        ]
    )

    selection, meta = select(
        candidates_json,
        _slots_json(),
        duration_s=20.0,
        client=client,
        session_dir=tmp_path,
    )

    assert selection == _selection_payload()
    assert meta["llm_attempts"] == 2
    attempt_1 = json.loads((tmp_path / "selection_attempt_1.json").read_text())
    assert attempt_1["status"] == "error"
    assert (tmp_path / "selection_attempt_2.json").exists()


def test_select_returns_none_on_persistent_malformed_json(tmp_path) -> None:
    jpg = tmp_path / "f.jpg"
    jpg.write_bytes(b"x")
    candidates_json = {"candidates": [_cand("c1", [0], jpg)]}
    client = _FakeClient(
        [
            _FakeInteraction("completed", "not json"),
            _FakeInteraction("completed", "still not json"),
        ]
    )

    selection, meta = select(
        candidates_json,
        _slots_json(),
        duration_s=20.0,
        client=client,
        session_dir=tmp_path,
    )

    assert selection is None
    assert meta["llm_attempts"] == 2


def test_theme_switches_prompt_wording() -> None:
    assert "explosividad" in build_system_prompt("training")
    yoga = build_system_prompt("yoga")
    assert "savasana" in yoga and "Solo tipo peak" in yoga
    assert "yoga" in build_user_prompt(6.0, _slots_json(), [], "yoga")
    assert "Hyrox" in build_user_prompt(6.0, _slots_json(), [])




def test_build_parts_sends_absolute_speed_and_prompt_explains_it(tmp_path) -> None:
    jpg = tmp_path / "p.jpg"
    jpg.write_bytes(b"\xff\xd8\xff")
    cand = {
        "id": "c1",
        "kind": "peak",
        "src": "a.mov",
        "multi_subject": False,
        "kp_speed_abs": 2.345,
        "peak_frames": [str(jpg)],
    }
    text = build_parts([cand], "prompt")[0]["text"]
    assert "velocidad=2.35" in text
    del cand["kp_speed_abs"]
    assert "velocidad=0.00" in build_parts([cand], "p")[0]["text"]
    system = build_system_prompt("training")
    assert "velocidad" in system


def test_hook_copy_schema_requires_contract_fields() -> None:
    schema = hook_copy_schema()
    assert schema["required"] == ["candidate_id", "evidence", "hook_line"]
    assert schema["properties"]["evidence"]["maxItems"] == 3


def _hook_cand():
    return {
        "id": "hook1",
        "kind": "peak",
        "src": "a.mov",
        "multi_subject": False,
        "kp_speed_abs": 1.5,
        "peak_frames": [],
    }


def test_hook_copy_accepts_matching_candidate_with_evidence(tmp_path) -> None:
    payload = {
        "candidate_id": "hook1",
        "evidence": ["barra en el suelo", "atleta agachado"],
        "hook_line": "la barra despega del suelo",
    }
    client = _FakeClient([_FakeInteraction("completed", json.dumps(payload))])

    result = generate_hook_copy(
        _hook_cand(), "deadlift", "training", client, "test-model", tmp_path
    )

    assert result["hook_line"] == "la barra despega del suelo"
    assert result["evidence"] == payload["evidence"]
    assert result["rejected"] is None
    assert result["source"] == "llm"
    assert (tmp_path / "hooks.json").exists()
    assert json.loads((tmp_path / "hooks.json").read_text())["hook_line"] == (
        "la barra despega del suelo"
    )


def test_hook_copy_rejects_candidate_id_mismatch(tmp_path) -> None:
    payload = {
        "candidate_id": "other",
        "evidence": ["barra en el suelo"],
        "hook_line": "la barra despega del suelo",
    }
    client = _FakeClient([_FakeInteraction("completed", json.dumps(payload))])

    result = generate_hook_copy(
        _hook_cand(), "deadlift", "training", client, "test-model", tmp_path
    )

    assert result["hook_line"] == ""
    assert result["rejected"] == "candidate_id_mismatch"
    assert len(client.interactions.calls) == 1


def test_hook_copy_abstains_on_empty_line(tmp_path) -> None:
    payload = {"candidate_id": "hook1", "evidence": [], "hook_line": ""}
    client = _FakeClient([_FakeInteraction("completed", json.dumps(payload))])

    result = generate_hook_copy(
        _hook_cand(), "deadlift", "training", client, "test-model", tmp_path
    )

    assert result["hook_line"] == ""
    assert result["rejected"] is None
    assert len(client.interactions.calls) == 1


def test_hook_copy_rejects_line_without_evidence(tmp_path) -> None:
    payload = {
        "candidate_id": "hook1",
        "evidence": [],
        "hook_line": "la barra despega del suelo",
    }
    client = _FakeClient([_FakeInteraction("completed", json.dumps(payload))])

    result = generate_hook_copy(
        _hook_cand(), "deadlift", "training", client, "test-model", tmp_path
    )

    assert result["hook_line"] == ""
    assert result["rejected"] == "no_evidence"


def test_hook_copy_override_skips_llm(tmp_path) -> None:
    client = _FakeClient([])

    result = generate_hook_copy(
        _hook_cand(),
        "deadlift",
        "training",
        client,
        "test-model",
        tmp_path,
        hook_line_override="Del operador",
    )

    assert result["hook_line"] == "Del operador"
    assert result["source"] == "override"
    assert result["cost_usd"] == 0.0
    assert client.interactions.calls == []
