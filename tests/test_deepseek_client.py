"""Adaptador DeepSeek (OpenAI SDK): misma forma que interactions.create()."""

from __future__ import annotations

import json
from unittest.mock import Mock, patch

import pytest

from edl_agent.llm.deepseek_client import deepseek_client

PARTS = [
    {"type": "text", "text": "id=c1"},
    {
        "type": "image",
        "data": "YmFzZTY0",
        "mime_type": "image/jpeg",
        "resolution": "low",
    },
    {"type": "text", "text": "prompt"},
]
GENERATION_CONFIG = {
    "thinking_level": "low",
    "temperature": 0.2,
    "max_output_tokens": 1000,
}
RESPONSE_FORMAT = {
    "type": "text",
    "mime_type": "application/json",
    "schema": {"type": "object"},
}


def _fake_response(
    *,
    finish_reason="stop",
    tool_arguments=None,
    prompt_tokens=500,
    completion_tokens=50,
):
    response = Mock()
    choice = Mock()
    choice.finish_reason = finish_reason
    if tool_arguments is None:
        choice.message.tool_calls = None
    else:
        tool_call = Mock()
        tool_call.function.arguments = json.dumps(tool_arguments)
        choice.message.tool_calls = [tool_call]
    response.choices = [choice]
    response.usage.prompt_tokens = prompt_tokens
    response.usage.completion_tokens = completion_tokens
    return response


def test_create_maps_tool_call_to_interaction_shape() -> None:
    client = deepseek_client(api_key="test")
    response = _fake_response(tool_arguments={"selected": []})
    with patch.object(
        client.interactions._client.chat.completions,
        "create",
        return_value=response,
    ) as create:
        interaction = client.interactions.create(
            model="deepseek-flash",
            system_instruction="SYS",
            input=PARTS,
            response_format=RESPONSE_FORMAT,
            generation_config=GENERATION_CONFIG,
        )

    kwargs = create.call_args.kwargs
    assert kwargs["tool_choice"] == {
        "type": "function",
        "function": {"name": "emit_selection"},
    }
    assert kwargs["tools"][0]["function"]["parameters"] == {"type": "object"}
    assert kwargs["messages"][1]["content"][1]["image_url"]["url"] == (
        "data:image/jpeg;base64,YmFzZTY0"
    )
    assert interaction.status == "completed"
    assert json.loads(interaction.output_text) == {"selected": []}
    assert interaction.usage.model_dump() == {
        "total_input_tokens": 500,
        "total_output_tokens": 50,
        "total_thought_tokens": 0,
    }


def test_create_marks_incomplete_on_length() -> None:
    client = deepseek_client(api_key="test")
    response = _fake_response(finish_reason="length", tool_arguments={"selected": []})
    with patch.object(
        client.interactions._client.chat.completions,
        "create",
        return_value=response,
    ):
        interaction = client.interactions.create(
            model="deepseek-flash",
            system_instruction="s",
            input=[],
            response_format=RESPONSE_FORMAT,
            generation_config=GENERATION_CONFIG,
        )
    assert interaction.status == "incomplete"


def test_create_raises_clear_error_when_no_tool_call_returned() -> None:
    client = deepseek_client(api_key="test")
    response = _fake_response(finish_reason="stop", tool_arguments=None)
    response.model_dump_json.return_value = "{}"
    with (
        patch.object(
            client.interactions._client.chat.completions,
            "create",
            return_value=response,
        ),
        pytest.raises(ValueError, match="no tool call"),
    ):
        client.interactions.create(
            model="deepseek-flash",
            system_instruction="s",
            input=[],
            response_format=RESPONSE_FORMAT,
            generation_config=GENERATION_CONFIG,
        )


def test_vision_guard_raises_for_non_vision_model() -> None:
    client = deepseek_client(api_key="test")
    with pytest.raises(ValueError, match="no vision support"):
        client.interactions.create(
            model="deepseek-v4-pro",
            system_instruction="s",
            input=PARTS,
            response_format=RESPONSE_FORMAT,
            generation_config=GENERATION_CONFIG,
        )


def test_vision_guard_allows_vision_model() -> None:
    client = deepseek_client(api_key="test")
    response = _fake_response(tool_arguments={"selected": []})
    with patch.object(
        client.interactions._client.chat.completions,
        "create",
        return_value=response,
    ):
        interaction = client.interactions.create(
            model="deepseek-flash",
            system_instruction="s",
            input=PARTS,
            response_format=RESPONSE_FORMAT,
            generation_config=GENERATION_CONFIG,
        )
    assert interaction.status == "completed"
