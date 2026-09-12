"""#5 Selector LLM: peticion inline-image, schema y reintentos por incomplete."""

from __future__ import annotations

import json

from edl_agent.selector import admissible_candidates, build_parts, select


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
        return self._responses.pop(0)


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
        "text": "id=c1 kind=peak src=a.mov multi_subject=False",
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
