"""Anthropic-SDK-backed client, shared by real Anthropic and DeepSeek.

DeepSeek exposes an Anthropic-compatible endpoint
(`https://api.deepseek.com/anthropic`) that the official `anthropic` SDK
talks to unmodified given a matching `base_url`, so one adapter class
serves both providers; only `base_url`, the API key, and (for DeepSeek) the
set of vision-capable model names differ.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

import anthropic

DEEPSEEK_BASE_URL = "https://api.deepseek.com/anthropic"
DEEPSEEK_VISION_MODELS = frozenset({"deepseek-flash", "deepseek-v4-flash-vision-exp"})


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

    def __init__(
        self, client: anthropic.Anthropic, vision_models: frozenset[str] | None
    ) -> None:
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
        """Send one Messages API request, mimicking `genai...interactions.create`.

        Args:
            model: Model name (e.g. `"claude-sonnet-5"`, `"deepseek-flash"`).
            system_instruction: System prompt text.
            input: Message parts, each a dict with `type` (`"text"` or
                `"image"`); text parts have `text` (str), image parts have
                `data` (str, base64-encoded image bytes) and `mime_type`.
            response_format: Structured-output spec; only `schema` (dict,
                JSON schema) is read and sent as a forced tool call, since
                the Messages API has no native `response_format` param.
            generation_config: Generation params; reads `temperature`
                (float) and `max_output_tokens` (int). `thinking_level` is
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

        Raises:
            ValueError: If `input` contains an image part and `model` isn't
                in this client's `vision_models` allowlist (DeepSeek only;
                real Anthropic has no restriction).
        """
        if self._vision_models is not None:
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
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": p["mime_type"],
                    "data": p["data"],
                },
            }
            for p in input
        ]
        tool = {
            "name": _TOOL_NAME,
            "description": "Emite la selección de candidatos.",
            "input_schema": response_format["schema"],
        }

        message = self._client.messages.create(
            model=model,
            max_tokens=generation_config["max_output_tokens"],
            temperature=generation_config["temperature"],
            system=system_instruction,
            messages=[{"role": "user", "content": content}],
            tools=[tool],
            tool_choice={"type": "tool", "name": _TOOL_NAME},
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

    Backed by the `anthropic` SDK; works for real Anthropic and for
    DeepSeek's Anthropic-compatible endpoint (see `deepseek_client`).
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        vision_models: frozenset[str] | None = None,
    ) -> None:
        self.sdk_version = anthropic.__version__
        client = anthropic.Anthropic(api_key=api_key, base_url=base_url)
        self.interactions = _Interactions(client, vision_models)


def anthropic_client(api_key: str | None = None) -> ClaudeCompatibleClient:
    """Build a client for real Anthropic (Claude).

    Args:
        api_key: Anthropic API key; defaults via `ANTHROPIC_API_KEY`, read
            by the `anthropic` SDK's own constructor, not read manually
            here.

    Returns:
        `ClaudeCompatibleClient` with no vision-model restriction — all
        current Claude models accept images.
    """
    return ClaudeCompatibleClient(api_key=api_key)


def deepseek_client(api_key: str | None = None) -> ClaudeCompatibleClient:
    """Build a client for DeepSeek, via its Anthropic-compatible endpoint.

    Args:
        api_key: DeepSeek API key; defaults via `DEEPSEEK_API_KEY` (read
            manually, since it isn't the `anthropic` SDK's default env var).

    Returns:
        `ClaudeCompatibleClient` pointed at DeepSeek's Anthropic-compatible
        base URL, restricted to `DEEPSEEK_VISION_MODELS` for image inputs.
    """
    return ClaudeCompatibleClient(
        api_key=api_key or os.environ.get("DEEPSEEK_API_KEY"),
        base_url=DEEPSEEK_BASE_URL,
        vision_models=DEEPSEEK_VISION_MODELS,
    )
