"""DeepSeek client, via its native OpenAI-compatible endpoint.

DeepSeek's own docs recommend the OpenAI SDK over their Anthropic-compat
surface (`https://api-docs.deepseek.com/`), so this talks `chat.completions`
directly rather than going through the Anthropic-shaped adapter.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

import openai

if TYPE_CHECKING:
    from openai.types.chat import (
        ChatCompletionMessageParam,
        ChatCompletionToolParam,
    )

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_VISION_MODELS = frozenset({"deepseek-flash", "deepseek-v4-flash-vision-exp"})

_TOOL_NAME = "emit_selection"


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


class _Interactions:
    """Backs `DeepSeekClient.interactions`; calls the Chat Completions API."""

    def __init__(self, client: openai.OpenAI, vision_models: frozenset[str]) -> None:
        self._client = client
        self._vision_models = vision_models

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
        """Send one Chat Completions request, mimicking `genai...interactions.create`.

        Args:
            model: DeepSeek model name (e.g. `"deepseek-flash"`).
            system_instruction: System prompt text.
            input: Message parts, each a dict with `type` (`"text"` or
                `"image"`); text parts have `text` (str), image parts have
                `data` (str, base64-encoded image bytes) and `mime_type`.
            response_format: Structured-output spec; only `schema` (dict,
                JSON schema) is read and sent as a forced function call,
                since Chat Completions has no native `response_format`
                param for arbitrary schemas.
            generation_config: Generation params; reads
                `max_output_tokens` (int). `temperature` and
                `thinking_level` are ignored, same as `AnthropicClient` —
                thinking is explicitly disabled to keep the forced tool
                call deterministic.
            **_: Ignored extra keyword arguments, for interface parity with
                `genai.Client.interactions.create`.

        Returns:
            `_Interaction` with `status` (`"completed"` or `"incomplete"`
            if `finish_reason` was `"length"`), `output_text` (the tool
            call's arguments, already a JSON string), and `usage`.

        Raises:
            ValueError: If `input` contains an image part and `model` isn't
                in this client's `vision_models` allowlist, or if DeepSeek
                didn't return the forced tool call.
        """
        has_images = any(p["type"] == "image" for p in input)
        if has_images and model not in self._vision_models:
            msg = (
                f"Model {model!r} has no vision support; use one of "
                f"{sorted(self._vision_models)} for image inputs."
            )
            raise ValueError(msg)

        content = [
            {"type": "text", "text": p["text"]}
            if p["type"] == "text"
            else {
                "type": "image_url",
                "image_url": {"url": f"data:{p['mime_type']};base64,{p['data']}"},
            }
            for p in input
        ]
        tool: ChatCompletionToolParam = {
            "type": "function",
            "function": {
                "name": _TOOL_NAME,
                "description": "Emite la selección de candidatos.",
                "parameters": response_format["schema"],
            },
        }

        messages: list[ChatCompletionMessageParam] = cast(
            "list[ChatCompletionMessageParam]",
            [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": content},
            ],
        )
        tools: list[ChatCompletionToolParam] = [tool]

        response = self._client.chat.completions.create(
            model=model,
            max_tokens=generation_config["max_output_tokens"],
            messages=messages,
            tools=tools,
            tool_choice={"type": "function", "function": {"name": _TOOL_NAME}},
            extra_body={"thinking": {"type": "disabled"}},
        )

        choice = response.choices[0]
        if not choice.message.tool_calls:
            msg = (
                f"DeepSeek returned no tool call (finish_reason="
                f"{choice.finish_reason!r}); response: {response.model_dump_json()}"
            )
            raise ValueError(msg)
        tool_call = choice.message.tool_calls[0]

        status = "incomplete" if choice.finish_reason == "length" else "completed"
        usage = _Usage(
            total_input_tokens=response.usage.prompt_tokens if response.usage else 0,
            total_output_tokens=response.usage.completion_tokens
            if response.usage
            else 0,
        )
        # Re-serialized via json.loads/dumps to normalize formatting and fail
        # fast on malformed JSON, matching the Anthropic adapter's contract.
        if not hasattr(tool_call, "function") or not hasattr(
            tool_call.function, "arguments"
        ):
            msg = "Tool call has no function.arguments"
            raise ValueError(msg)
        func_args = cast("str", tool_call.function.arguments)
        return _Interaction(
            status=status,
            output_text=json.dumps(json.loads(func_args)),
            usage=usage,
        )


class DeepSeekClient:
    """Drop-in for `genai.Client`'s `.interactions.create()` shape.

    Backed by the `openai` SDK, pointed at DeepSeek's native OpenAI-compatible
    endpoint (DeepSeek's own recommended integration path).
    """

    def __init__(self, api_key: str | None = None) -> None:
        self.sdk_version = openai.__version__
        client = openai.OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)
        self.interactions = _Interactions(client, DEEPSEEK_VISION_MODELS)


def deepseek_client(api_key: str | None = None) -> DeepSeekClient:
    """Build a client for DeepSeek, via its native OpenAI-compatible endpoint.

    Args:
        api_key: DeepSeek API key; defaults via `DEEPSEEK_API_KEY` (read
            manually, since it isn't the `openai` SDK's default env var).

    Returns:
        `DeepSeekClient`.
    """
    return DeepSeekClient(api_key=api_key or os.environ.get("DEEPSEEK_API_KEY"))
