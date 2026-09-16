"""Factory for LLM provider clients, selectable per run.

Every client returned here is duck-typed to `.interactions.create(...)`
(see `edl_agent.selector.pipeline.select`) and exposes an `.sdk_version`
attribute so callers can report which SDK actually served a given run.
"""

from __future__ import annotations

from typing import Any

PROVIDERS = ("gemini", "anthropic", "deepseek", "ollama")


def get_client(provider: str, **kwargs: Any) -> Any:  # noqa: ANN401 (duck-typed return)
    """Build an LLM client for the given provider.

    Args:
        provider: One of `PROVIDERS`.
        **kwargs: Passed through to the provider's client constructor
            (e.g. `api_key` for `"anthropic"`/`"deepseek"`, `base_url` for
            `"ollama"`).

    Returns:
        A client exposing `.interactions.create(...)` and `.sdk_version`.

    Raises:
        ValueError: If `provider` isn't one of `PROVIDERS`.
    """
    if provider == "gemini":
        from google import genai

        client: Any = genai.Client(**kwargs)
        client.sdk_version = genai.__version__
        return client
    if provider == "anthropic":
        from edl_agent.llm.anthropic_client import anthropic_client

        return anthropic_client(**kwargs)
    if provider == "deepseek":
        from edl_agent.llm.deepseek_client import deepseek_client

        return deepseek_client(**kwargs)
    if provider == "ollama":
        from edl_agent.llm.ollama_client import OllamaClient

        client: Any = OllamaClient(**kwargs)
        client.sdk_version = None
        return client
    msg = f"Unknown provider: {provider!r}, expected one of {PROVIDERS}"
    raise ValueError(msg)
