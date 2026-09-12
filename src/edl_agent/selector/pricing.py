"""LLM call cost accounting, #11."""

from __future__ import annotations

# #11: USD per 1M tokens, in effect until 2026-12-31 (same rate for
# 3.7/3.8-flash). Thinking tokens are billed as output.
PRICING_PER_MTOK = {"gemini-3.7-flash": (0.75, 3.75), "gemini-3.8-flash": (0.75, 3.75)}


def _cost_usd(usage: dict | None, model: str) -> float:
    """Compute the USD cost of one LLM call from its token usage, per #11.

    Args:
        usage: Usage dict (see `_usage_dict`) with `total_input_tokens`,
            `total_output_tokens`, `total_thought_tokens`; `None` if usage
            is unavailable.
        model: Model name, looked up in `PRICING_PER_MTOK`.

    Returns:
        Cost in USD; `0.0` if `usage` is `None` or `model` has no entry in
        `PRICING_PER_MTOK` (e.g. an Ollama model).
    """
    if usage is None or model not in PRICING_PER_MTOK:
        return 0.0
    input_price, output_price = PRICING_PER_MTOK[model]
    input_tokens = usage.get("total_input_tokens", 0) or 0
    output_tokens = (usage.get("total_output_tokens", 0) or 0) + (
        usage.get("total_thought_tokens", 0) or 0
    )
    return input_tokens * input_price / 1e6 + output_tokens * output_price / 1e6
