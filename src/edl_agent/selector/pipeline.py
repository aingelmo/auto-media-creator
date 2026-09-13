"""Call the LLM selector with retries, #5.1+#5.6."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests

from edl_agent.selector._common import DEFAULTS
from edl_agent.selector.client import _sdk_version, _usage_dict
from edl_agent.selector.pricing import _cost_usd
from edl_agent.selector.prompts import (
    REINFORCED_SUFFIX,
    SYSTEM_PROMPT,
    admissible_candidates,
    build_parts,
    build_user_prompt,
    selection_schema,
)


def select(
    candidates_json: dict,
    slots_json: dict,
    duration_s: float,
    client: Any,  # noqa: ANN401 (duck-typed: google-genai Client or OllamaClient)
    session_dir: Path,
    config: dict[str, Any] | None = None,
) -> tuple[dict | None, dict]:
    """Call the LLM selector with retries, per #5.1+#5.6.

    Args:
        candidates_json: Parsed `candidates.json`, with a `candidates` key.
        slots_json: Parsed `slots.json`, with a `slots` key.
        duration_s: Target reel duration, in seconds.
        client: A `google.genai.Client`-shaped object (or `OllamaClient`),
            duck-typed: only `.interactions.create(...)` is called.
        session_dir: Session directory to write
            `selection_attempt_N.json` files to.
        config: Overrides merged over `DEFAULTS` (`model`,
            `thinking_level`, `thinking_level_many_candidates`,
            `many_candidates_threshold`, `temperature`,
            `max_output_tokens`, `max_attempts`).

    Returns:
        `(selection, meta)`:
        - `selection`: parsed LLM output (see `selection_schema`), or
          `None` if every attempt (up to `max_attempts`, #5.6) returned
          `status == "incomplete"` — in that case the whole role
          assignment is left to the rules fallback (#8.6).
        - `meta`: dict with `model`, `sdk_version`, `api_revision` (always
          `None`; [validate], not exposed by the high-level SDK),
          `llm_attempts` (int), `llm_usage` (dict from the last attempt, or
          `None`), `llm_cost_usd` (float, summed over all attempts).
    """
    config = {**DEFAULTS, **(config or {})}
    session_dir = Path(session_dir)

    candidates = admissible_candidates(candidates_json, slots_json)
    user_prompt = build_user_prompt(duration_s, slots_json, candidates)
    parts = build_parts(candidates, user_prompt)
    thinking_level = (
        config["thinking_level_many_candidates"]
        if len(candidates) >= config["many_candidates_threshold"]
        else config["thinking_level"]
    )

    selection = None
    attempts_usage: list[dict | None] = []
    total_cost = 0.0
    system_prompt = SYSTEM_PROMPT

    for attempt in range(1, config["max_attempts"] + 1):
        try:
            interaction = client.interactions.create(
                model=config["model"],
                system_instruction=system_prompt,
                input=parts,
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": selection_schema(),
                },
                generation_config={
                    "thinking_level": thinking_level,
                    "temperature": config["temperature"],
                    "max_output_tokens": config["max_output_tokens"],
                },
            )
            usage = _usage_dict(getattr(interaction, "usage", None))
            cost = _cost_usd(usage, config["model"])
            attempt_record = {
                "attempt": attempt,
                "status": interaction.status,
                "usage": usage,
                "cost_usd": cost,
            }
            if interaction.status != "incomplete":
                attempt_record["output"] = json.loads(interaction.output_text)
        except (requests.RequestException, json.JSONDecodeError) as exc:
            usage, cost = None, 0.0
            attempt_record = {
                "attempt": attempt,
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
                "usage": None,
                "cost_usd": 0.0,
            }

        attempts_usage.append(usage)
        total_cost += cost

        with (session_dir / f"selection_attempt_{attempt}.json").open("w") as f:
            json.dump(attempt_record, f, indent=2, ensure_ascii=False)

        if attempt_record["status"] not in ("incomplete", "error"):
            selection = attempt_record["output"]
            break
        system_prompt = SYSTEM_PROMPT + REINFORCED_SUFFIX  # #5.6: reinforced retry

    meta = {
        "model": config["model"],
        "sdk_version": _sdk_version(),
        "api_revision": None,  # [validate] not exposed by the high-level SDK
        "llm_attempts": len(attempts_usage),
        "llm_usage": attempts_usage[-1] if attempts_usage else None,
        "llm_cost_usd": total_cost,
    }
    return selection, meta
