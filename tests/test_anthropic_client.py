"""Adaptador Anthropic: misma forma que interactions.create()."""

from __future__ import annotations

import json
from unittest.mock import Mock, patch

from edl_agent.llm.anthropic_client import anthropic_client

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


def _fake_message(
    *, stop_reason="end_turn", tool_input=None, input_tokens=500, output_tokens=50
):
    message = Mock()
    message.stop_reason = stop_reason
    tool_input = tool_input if tool_input is not None else {}
    message.content = [Mock(type="tool_use", input=tool_input)]
    message.usage = Mock()
    message.usage.model_dump.return_value = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }
    return message


def test_create_maps_tool_use_to_interaction_shape() -> None:
    client = anthropic_client(api_key="test")
    message = _fake_message(tool_input={"selected": []})
    with patch.object(
        client.interactions._client.messages, "create", return_value=message  # noqa: SLF001
    ) as create:
        interaction = client.interactions.create(
            model="claude-sonnet-5",
            system_instruction="SYS",
            input=PARTS,
            response_format=RESPONSE_FORMAT,
            generation_config=GENERATION_CONFIG,
        )

    kwargs = create.call_args.kwargs
    assert kwargs["tool_choice"] == {"type": "tool", "name": "emit_selection"}
    assert kwargs["tools"][0]["input_schema"] == {"type": "object"}
    assert kwargs["messages"][0]["content"][1]["source"]["data"] == "YmFzZTY0"
    assert interaction.status == "completed"
    assert json.loads(interaction.output_text) == {"selected": []}
    assert interaction.usage.model_dump() == {
        "total_input_tokens": 500,
        "total_output_tokens": 50,
        "total_thought_tokens": 0,
    }


def test_create_marks_incomplete_on_max_tokens() -> None:
    client = anthropic_client(api_key="test")
    message = _fake_message(stop_reason="max_tokens")
    with patch.object(
        client.interactions._client.messages, "create", return_value=message  # noqa: SLF001
    ):
        interaction = client.interactions.create(
            model="claude-sonnet-5",
            system_instruction="s",
            input=[],
            response_format=RESPONSE_FORMAT,
            generation_config=GENERATION_CONFIG,
        )
    assert interaction.status == "incomplete"
