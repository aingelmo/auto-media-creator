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
            `"ollama"`). An omitted/`None` `api_key` falls back to
            `edl_agent.keys.resolve_api_key` (explicit > env > the
            UI-persisted file), so CLI and web runs share one resolution.

    Returns:
        A client exposing `.interactions.create(...)` and `.sdk_version`.

    Raises:
        ValueError: If `provider` isn't one of `PROVIDERS`.
    """
    if kwargs.get("api_key") is None:
        from edl_agent.keys import resolve_api_key

        resolved = resolve_api_key(provider)
        if resolved is not None:
            kwargs["api_key"] = resolved
        else:
            # Never hand an explicit `None` down: ctors that take no
            # `api_key` (e.g. `OllamaClient`) would raise `TypeError`,
            # and SDK-default env fallback only triggers on absence.
            kwargs.pop("api_key", None)
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
