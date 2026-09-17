"""LLM call cost accounting, #11."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

# #11: USD per 1M tokens, in effect until 2026-12-31 (same rate for
# 3.7/3.8-flash). Thinking tokens are billed as output.
# claude-sonnet-5/claude-haiku-4-5: platform.claude.com/docs/en/about-claude/pricing
# deepseek-flash: api-docs.deepseek.com/quick_start/pricing (deepseek-v4-flash).
# Off-peak cache-miss rate used as default; peak rate is exactly double.
PRICING_PER_MTOK = {
    "gemini-3.7-flash": (0.75, 3.75),
    "gemini-3.8-flash": (0.75, 3.75),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "deepseek-flash": (0.22, 0.66),
}


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


def append_cost_entry(
    session_dir: Path, stage: str, model: str, usage: dict | None, cost: float
) -> None:
    """Append one LLM call's cost to `session_dir/costs.jsonl`, an append-only ledger.

    Unlike `selection.json`/`selection_meta.json`/`hooks.json`, this file is
    never cleared by a regenerate (`web.artifacts.clear_stage_artifacts`) or
    overwritten by a retry loop, so it accumulates the true lifetime cost of
    a session across every regenerate/retry, not just the latest run.

    Args:
        session_dir: Session directory to append `costs.jsonl` to.
        stage: Pipeline stage that made the call, e.g. `"selection"`,
            `"hooks"`.
        model: Model name passed to the LLM client.
        usage: Usage dict (see `_usage_dict`), or `None` if the request
            failed before any tokens were billed (skipped in that case).
        cost: USD cost, as computed by `_cost_usd`.
    """
    if usage is None:
        return
    entry = {
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        "stage": stage,
        "model": model,
        "usage": usage,
        "cost_usd": cost,
    }
    with (Path(session_dir) / "costs.jsonl").open("a") as f:
        f.write(json.dumps(entry) + "\n")
