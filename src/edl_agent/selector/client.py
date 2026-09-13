"""SDK-shaped helpers, duck-typed over all `edl_agent.llm` clients."""

from __future__ import annotations

from typing import Any


def _usage_dict(usage: Any) -> dict | None:  # noqa: ANN401 (usage is an SDK-specific object, duck-typed)
    """Normalize an SDK usage object into a plain dict.

    Args:
        usage: SDK-specific usage object (has `.model_dump()`, e.g. genai's
            or the `anthropic`-backed adapters', or is dict-like, e.g.
            `OllamaClient`'s `_Usage`), or `None`.

    Returns:
        Dict with `total_input_tokens`, `total_output_tokens`,
        `total_thought_tokens`, or `None` if `usage` is `None`.
    """
    if usage is None:
        return None
    return usage.model_dump() if hasattr(usage, "model_dump") else dict(usage)
