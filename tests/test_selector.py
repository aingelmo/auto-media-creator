"""#5 Selector LLM: peticion inline-image, schema y reintentos por incomplete."""

from __future__ import annotations

import json

import requests

from edl_agent.selector import admissible_candidates, build_parts, select
from edl_agent.selector.hooks import HOOK_ANGLES, generate_hooks, hooks_schema
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


def test_hooks_schema_has_six_item_lines_with_angle_enum() -> None:
    schema = hooks_schema()
    lines = schema["properties"]["lines"]
    assert lines["minItems"] == lines["maxItems"] == 6
    assert lines["items"]["properties"]["angle"]["enum"] == [k for k, _ in HOOK_ANGLES]


def _hook_cand():
    return {
        "id": "hook1",
        "kind": "peak",
        "src": "a.mov",
        "multi_subject": False,
        "kp_speed_abs": 1.5,
        "peak_frames": [],
    }


def _hooks_payload(lines):
    return {"lines": lines}


def test_generate_hooks_cleans_dedupes_and_writes_hooks_json(tmp_path) -> None:
    lines = [
        {"angle": "reto", "text": "aguanta un segundo mas"},
        {"angle": "pregunta", "text": "aguanta un segundo mas"},  # dup, dropped
        {"angle": "momento", "text": " ".join(["palabra"] * 9)},  # too long, dropped
        {"angle": "comunidad", "text": "hoy toca dar el cien por cien"},
        {"angle": "contraste", "text": "antes dudabas, ahora no"},
        {"angle": "confesion", "text": "esto me costo mas de lo que parece"},
    ]
    client = _FakeClient(
        [_FakeInteraction("completed", json.dumps(_hooks_payload(lines)))]
    )

    result = generate_hooks(
        _hook_cand(), "back squat", "training", client, "test-model", tmp_path
    )

    assert len(result["lines"]) == 4
    texts = [line["text"] for line in result["lines"]]
    assert texts.count("aguanta un segundo mas") == 1
    assert (tmp_path / "hooks.json").exists()
    assert json.loads((tmp_path / "hooks.json").read_text())["lines"] == result["lines"]


def test_generate_hooks_retries_once_when_fewer_than_three_survive(tmp_path) -> None:
    bad = _hooks_payload([{"angle": "reto", "text": ""}] * 6)
    good = _hooks_payload(
        [
            {"angle": "reto", "text": "vamos, una mas"},
            {"angle": "pregunta", "text": "hasta donde llegas hoy"},
            {"angle": "momento", "text": "asi se levanta la barra"},
        ]
    )
    client = _FakeClient(
        [
            _FakeInteraction("completed", json.dumps(bad)),
            _FakeInteraction("completed", json.dumps(good)),
        ]
    )

    result = generate_hooks(
        _hook_cand(), "back squat", "training", client, "test-model", tmp_path
    )

    assert len(result["lines"]) == 3
    assert len(client.interactions.calls) == 2
