"""SDK-shaped helpers, duck-typed over google-genai and OllamaClient."""

from __future__ import annotations

from typing import Any


def _usage_dict(usage: Any) -> dict | None:  # noqa: ANN401 (usage is an SDK-specific object, duck-typed)
    """Normalize an SDK usage object into a plain dict.

    Args:
        usage: SDK-specific usage object (has `.model_dump()`, e.g. genai's,
            or is dict-like, e.g. `OllamaClient`'s `_Usage`), or `None`.

    Returns:
        Dict with `total_input_tokens`, `total_output_tokens`,
        `total_thought_tokens`, or `None` if `usage` is `None`.
    """
    if usage is None:
        return None
    return usage.model_dump() if hasattr(usage, "model_dump") else dict(usage)


def _sdk_version() -> str | None:
    """Return the installed `google-genai` SDK version, if available.

    Returns:
        `genai.__version__`, or `None` if the `google-genai` package isn't
        installed (e.g. when only `OllamaClient` is used).
    """
    try:
        from google import genai
    except ImportError:
        return None
    else:
        return genai.__version__
