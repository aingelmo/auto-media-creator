"""Adaptador Ollama: misma forma que google.genai.Client.interactions.create()."""

from __future__ import annotations

from unittest.mock import Mock, patch

from edl_agent.ollama_client import OllamaClient


def _fake_response(json_data):
    resp = Mock()
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    return resp


def test_create_maps_ollama_chat_response_to_interaction_shape() -> None:
    client = OllamaClient()
    parts = [
        {"type": "text", "text": "id=c1"},
        {
            "type": "image",
            "data": "YmFzZTY0",
            "mime_type": "image/jpeg",
            "resolution": "low",
        },
        {"type": "text", "text": "prompt"},
    ]
    data = {
        "message": {"role": "assistant", "content": '{"selected": []}'},
        "prompt_eval_count": 500,
        "eval_count": 50,
        "done_reason": "stop",
    }
    with patch(
        "edl_agent.ollama_client.requests.post", return_value=_fake_response(data)
    ) as post:
        interaction = client.interactions.create(
            model="qwen3-vl:8b-instruct",
            system_instruction="SYS",
            input=parts,
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": {"type": "object"},
            },
            generation_config={
                "thinking_level": "low",
                "temperature": 0.2,
                "max_output_tokens": 1000,
            },
        )

    payload = post.call_args.kwargs["json"]
    assert payload["messages"][1]["images"] == ["YmFzZTY0"]
    assert payload["format"] == {"type": "object"}
    assert interaction.status == "completed"
    assert interaction.output_text == '{"selected": []}'
    assert interaction.usage.model_dump() == {
        "total_input_tokens": 500,
        "total_output_tokens": 50,
        "total_thought_tokens": 0,
    }


def test_create_marks_incomplete_on_length_truncation() -> None:
    client = OllamaClient()
    data = {"message": {"content": "{}"}, "done_reason": "length"}
    with patch(
        "edl_agent.ollama_client.requests.post", return_value=_fake_response(data)
    ):
        interaction = client.interactions.create(
            model="m",
            system_instruction="s",
            input=[],
            response_format={"schema": {}},
            generation_config={},
        )
    assert interaction.status == "incomplete"
