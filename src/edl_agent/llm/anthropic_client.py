"""Anthropic-SDK-backed client for real Anthropic (Claude)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

import anthropic

if TYPE_CHECKING:
    from anthropic.types import MessageParam, ToolParam


@dataclass
class _Usage:
    """Token usage counters, shaped like the genai SDK's usage object."""

    total_input_tokens: int
    total_output_tokens: int
    total_thought_tokens: int = 0

    def model_dump(self) -> dict:
        """Return this usage as a plain dict, matching the genai SDK's method name.

        Returns:
            Dict with keys `total_input_tokens`, `total_output_tokens`,
            `total_thought_tokens`.
        """
        return {
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_thought_tokens": self.total_thought_tokens,
        }


@dataclass
class _Interaction:
    """Result of one `_Interactions.create` call, shaped like the genai SDK's result."""

    status: str
    output_text: str
    usage: _Usage = field(default_factory=lambda: _Usage(0, 0))


_TOOL_NAME = "emit_selection"


class _Interactions:
    """Backs `ClaudeCompatibleClient.interactions`; calls the Messages API."""

    def __init__(self, client: anthropic.Anthropic) -> None:
        self._client = client

    def create(
        self,
        *,
        model: str,
        system_instruction: str,
        input: list[dict],  # noqa: A002 (matches the Interactions API's `input` kwarg)
        response_format: dict,
        generation_config: dict,
        **_: object,
    ) -> _Interaction:
        """Send one Messages API request, mimicking `genai...interactions.create`.

        Args:
            model: Model name (e.g. `"claude-sonnet-5"`).
            system_instruction: System prompt text.
            input: Message parts, each a dict with `type` (`"text"` or
                `"image"`); text parts have `text` (str), image parts have
                `data` (str, base64-encoded image bytes) and `mime_type`.
            response_format: Structured-output spec; only `schema` (dict,
                JSON schema) is read and sent as a forced tool call, since
                the Messages API has no native `response_format` param.
            generation_config: Generation params; reads
                `max_output_tokens` (int). `temperature` is ignored — the
                Messages API dropped that param. `thinking_level` is
                ignored — the Messages API's extended-thinking mechanism
                (a token budget, not a level enum) has no clean equivalent,
                same as `OllamaClient`.
            **_: Ignored extra keyword arguments, for interface parity with
                `genai.Client.interactions.create`.

        Returns:
            `_Interaction` with `status` (`"completed"` or `"incomplete"`
            if `stop_reason` was `"max_tokens"`), `output_text` (the tool
            call's input, re-serialized to a JSON string so callers can
            `json.loads` it exactly like the other adapters), and `usage`.
        """
        content = [
            {"type": "text", "text": p["text"]}
            if p["type"] == "text"
            else {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": p["mime_type"],
                    "data": p["data"],
                },
            }
            for p in input
        ]
        tool: ToolParam = {
            "name": _TOOL_NAME,
            "description": "Emite la selección de candidatos.",
            "input_schema": response_format["schema"],
        }

        messages: list[MessageParam] = cast(
            "list[MessageParam]", [{"role": "user", "content": content}]
        )
        tools: list[ToolParam] = [tool]

        message = self._client.messages.create(
            model=model,
            max_tokens=generation_config["max_output_tokens"],
            system=system_instruction,
            messages=messages,
            tools=tools,
            tool_choice={"type": "tool", "name": _TOOL_NAME},
            thinking={"type": "disabled"},
        )

        tool_use = next(b for b in message.content if b.type == "tool_use")
        status = "incomplete" if message.stop_reason == "max_tokens" else "completed"
        raw_usage = message.usage.model_dump()
        usage = _Usage(
            total_input_tokens=raw_usage.get("input_tokens", 0) or 0,
            total_output_tokens=raw_usage.get("output_tokens", 0) or 0,
        )
        return _Interaction(
            status=status, output_text=json.dumps(tool_use.input), usage=usage
        )


class ClaudeCompatibleClient:
    """Drop-in for `genai.Client`'s `.interactions.create()` shape.

    Backed by the `anthropic` SDK, for real Anthropic (Claude).
    """

    def __init__(self, api_key: str | None = None) -> None:
        self.sdk_version = anthropic.__version__
        client = anthropic.Anthropic(api_key=api_key)
        self.interactions = _Interactions(client)


def anthropic_client(api_key: str | None = None) -> ClaudeCompatibleClient:
    """Build a client for real Anthropic (Claude).

    Args:
        api_key: Anthropic API key; defaults via `ANTHROPIC_API_KEY`, read
            by the `anthropic` SDK's own constructor, not read manually
            here.

    Returns:
        `ClaudeCompatibleClient`.
    """
    return ClaudeCompatibleClient(api_key=api_key)
