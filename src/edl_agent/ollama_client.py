"""Local Ollama client that mimics the `google.genai.Client` interface.

Exposes `.interactions.create(...)` so `selector.select()` can call it
unmodified, without spending on Gemini during early vision-prompt testing
(#5).

For manual/testing use only: it does not apply pricing (#11 does not cover
Ollama models; `_cost_usd` already returns 0.0 for models outside
`PRICING_PER_MTOK`) and there is no equivalent of `thinking_level` (ignored).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import requests

DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_NUM_CTX = 8192
# Ollama serves with a default of 4096 unless asked for more; with several
# candidates plus reference images the prompt approaches or exceeds that
# limit and the model returns truncated/corrupt JSON. 16384 spills to CPU on
# an RTX 2070 8GB with qwen3-vl:8b-instruct without improving reliability
# (see validation sessions 2026-09-11)


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
    """Backs `OllamaClient.interactions`, translating calls to Ollama's `/api/chat`."""

    def __init__(self, base_url: str, num_ctx: int = DEFAULT_NUM_CTX) -> None:
        self._base_url = base_url
        self._num_ctx = num_ctx

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
        """Send one chat request to Ollama, mimicking `genai...interactions.create`.

        Args:
            model: Ollama model name (e.g. `"qwen3-vl:8b-instruct"`).
            system_instruction: System prompt text.
            input: Message parts, each a dict with `type` (`"text"` or
                `"image"`); text parts have `text` (str), image parts have
                `data` (str, base64-encoded image bytes).
            response_format: Structured-output spec; only `schema` (dict,
                JSON schema) is read and passed to Ollama's `format` field.
            generation_config: Generation params; reads `temperature`
                (float) and `max_output_tokens` (int, mapped to Ollama's
                `num_predict`).
            **_: Ignored extra keyword arguments, for interface parity with
                `genai.Client.interactions.create` (e.g. `thinking_level`,
                which Ollama has no equivalent for).

        Returns:
            `_Interaction` with `status` (`"completed"` or `"incomplete"`
            if Ollama's `done_reason` was `"length"`), `output_text` (the
            raw JSON string from the model), and `usage`.

        Raises:
            requests.HTTPError: If the Ollama server returns a non-2xx
                response.
        """
        content_lines = [p["text"] for p in input if p["type"] == "text"]
        images = [p["data"] for p in input if p["type"] == "image"]

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": "\n".join(content_lines), "images": images},
            ],
            "format": response_format.get("schema"),
            "stream": False,
            "options": {
                "temperature": generation_config.get("temperature"),
                "num_predict": generation_config.get("max_output_tokens"),
                "num_ctx": self._num_ctx,
            },
        }
        resp = requests.post(f"{self._base_url}/api/chat", json=payload, timeout=600)
        resp.raise_for_status()
        data = resp.json()

        status = "incomplete" if data.get("done_reason") == "length" else "completed"
        usage = _Usage(
            total_input_tokens=data.get("prompt_eval_count", 0),
            total_output_tokens=data.get("eval_count", 0),
        )
        return _Interaction(
            status=status, output_text=data["message"]["content"], usage=usage
        )


class OllamaClient:
    """Local drop-in for `genai.Client`, backed by an Ollama server."""

    def __init__(
        self, base_url: str = DEFAULT_BASE_URL, num_ctx: int = DEFAULT_NUM_CTX
    ) -> None:
        self.interactions = _Interactions(base_url, num_ctx)
