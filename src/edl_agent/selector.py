"""Layer 3 - LLM selector (Gemini), #5.

Builds the inline-image request (#5.1) from the admissible candidates in
candidates.json, sends it via google-genai's Interactions API, and applies
retries on `status: "incomplete"` (#5.6). Saves each attempt as
`selection_attempt_N.json` in session_dir. The result (`selection`,
`selection_meta`) is passed straight to `session.run_planner`.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, Any] = {
    "model": "gemini-3.7-flash",
    "thinking_level": "low",
    "thinking_level_many_candidates": "medium",  # #5.1: >=30 candidatos
    "many_candidates_threshold": 30,
    "temperature": 0.2,
    "max_output_tokens": 16384,
    "max_attempts": 2,  # #5.6
}

# Canonical list of exercises, #5.5.
EXERCISES = [
    "back squat",
    "front squat",
    "overhead squat",
    "deadlift",
    "clean",
    "snatch",
    "jerk",
    "thruster",
    "pull-up",
    "muscle-up",
    "push-up",
    "burpee",
    "box jump",
    "wall ball",
    "kettlebell swing",
    "rowing",
    "bike",
    "ski erg",
    "run",
    "rope climb",
    "handstand",
    "double-under",
    "other",
]

SYSTEM_PROMPT = """Eres un editor de vídeo profesional especializado en Reels \
verticales (9:16) de gimnasio.

Recibes una lista de MOMENTOS CANDIDATOS. Cada candidato tiene un id, un tipo \
(peak = momento de acción, calm = momento estable, image = foto) y uno o tres \
fotogramas: justo antes del pico, el pico y justo después. Recibes también los \
SLOTS del montaje con su rol narrativo y una LISTA CANÓNICA DE EJERCICIOS.

Tu tarea es juzgar contenido, no calcular tiempos, coordenadas ni orden temporal.

1. RECHAZA los candidatos con: desenfoque en el fotograma central, sujeto fuera \
de encuadre o tapado, encuadre que no permite ver la ejecución, o contenido \
idéntico a otro candidato mejor del mismo clip.
2. SELECCIONA todos los demás y asigna a cada uno UN rol:
   - hook: máxima explosividad o impacto visual. Solo tipo peak.
   - close: sujeto estable, centrado, final limpio. Solo tipo calm o image.
   - develop: el resto. Prioriza variedad de ejercicios y planos donde se ve \
bien la técnica.
3. Asigna rank dentro de cada rol: 1 = mejor calidad. Sin huecos (1, 2, 3, …). \
El orden en el montaje lo decide otro sistema.
4. exercise: usa exactamente un nombre de la lista canónica; si no encaja, "other".
5. Si hay menos de 3 candidatos válidos para develop o ninguno para hook o close, \
explícalo en notes. No inventes candidatos ni fuerces rechazos para cumplir cuotas.

Reglas:
- Usa solo candidate_id existentes. No emitas tiempos ni coordenadas.
- reason: máximo 12 palabras. Responde únicamente con el JSON del schema."""

REINFORCED_SUFFIX = "\n\nreason: máximo 8 palabras."

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


USER_PROMPT_TEMPLATE = """OBJETIVO: Reel de {duration_s} s. Temática: resumen \
dinámico de entrenamiento.

SLOTS (N_SLOTS = {n_slots}): 1 hook, {n_develop} develop, 1 close.

LISTA CANÓNICA DE EJERCICIOS:
{exercises}

CANDIDATOS: {n_cand} (ids: {ids}). Los fotogramas de cada uno preceden a este \
mensaje, etiquetados con su id.

Genera la selección."""


def selection_schema() -> dict:
    """Build the output schema for Gemini's structured output, per #5.3.

    The `description` strings inside the schema are sent to the model
    verbatim (they are instructions, not documentation) and are kept in
    Spanish to match the rest of the prompt.

    Returns:
        JSON schema dict (draft-agnostic subset understood by Gemini's
        structured-output feature) requiring `selected` (list of
        `{candidate_id, role, rank, exercise, reason}`), `rejected` (list
        of `{candidate_id, reason}`), and `notes` (string).
    """
    return {
        "type": "object",
        "properties": {
            "selected": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "candidate_id": {"type": "string"},
                        "role": {
                            "type": "string",
                            "enum": ["hook", "develop", "close"],
                        },
                        "rank": {
                            "type": "integer",
                            "minimum": 1,
                            "description": (
                                "Calidad dentro de su rol. 1 = mejor. Sin huecos. "
                                "No es orden temporal."
                            ),
                        },
                        "exercise": {"type": "string", "enum": EXERCISES},
                        "reason": {
                            "type": "string",
                            "description": "Máximo 12 palabras.",
                        },
                    },
                    "required": ["candidate_id", "role", "rank", "exercise", "reason"],
                },
            },
            "rejected": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "candidate_id": {"type": "string"},
                        "reason": {
                            "type": "string",
                            "description": "Máximo 8 palabras.",
                        },
                    },
                    "required": ["candidate_id", "reason"],
                },
            },
            "notes": {
                "type": "string",
                "description": (
                    "Vacío salvo problemas globales (pocos candidatos válidos, "
                    "todo el material repetido, etc.)."
                ),
            },
        },
        "required": ["selected", "rejected", "notes"],
    }


def admissible_candidates(candidates_json: dict, slots_json: dict) -> list[dict]:
    """Filter to candidates that fit at least one slot, per #5.1.

    Only these are sent to the LLM; ones that can't fit anywhere would
    just waste prompt tokens.

    Args:
        candidates_json: Parsed `candidates.json`, with a `candidates` key
            (list of candidate dicts; reads `admits_slots`, list[int]).
        slots_json: Parsed `slots.json`, with a `slots` key (list of slot
            dicts; reads `slot`, int).

    Returns:
        Subset of `candidates_json["candidates"]` whose `admits_slots`
        intersects the session's slot indices.
    """
    slot_indices = {s["slot"] for s in slots_json["slots"]}
    return [
        c
        for c in candidates_json["candidates"]
        if set(c["admits_slots"]) & slot_indices
    ]


def build_user_prompt(
    duration_s: float, slots_json: dict, candidates: list[dict]
) -> str:
    """Fill in `USER_PROMPT_TEMPLATE` with the current session, per #5.1.

    Args:
        duration_s: Target reel duration, in seconds.
        slots_json: Parsed `slots.json`, with a `slots` key.
        candidates: Admissible candidates (see `admissible_candidates`);
            only their `id`s are used here.

    Returns:
        Filled-in user prompt text (in Spanish, matching `SYSTEM_PROMPT`).
    """
    slots = slots_json["slots"]
    n_develop = sum(1 for s in slots if s["role"] == "develop")
    return USER_PROMPT_TEMPLATE.format(
        duration_s=duration_s,
        n_slots=len(slots),
        n_develop=n_develop,
        exercises=", ".join(EXERCISES),
        n_cand=len(candidates),
        ids=", ".join(c["id"] for c in candidates),
    )


def build_parts(candidates: list[dict], user_prompt: str) -> list[dict]:
    """Build the text+image request parts, one set per candidate plus the prompt.

    Per #5.1: a low-resolution base64 image is sent per peak frame, so
    interactions stay within reasonable token/latency limits for `qwen3-vl`-
    class vision models.

    Args:
        candidates: Admissible candidates (see `admissible_candidates`).
            Reads `id`, `kind`, `src`, `multi_subject`, `peak_frames`
            (list[str], JPEG paths).
        user_prompt: Filled-in user prompt text, appended as the final
            part.

    Returns:
        List of part dicts, each either `{"type": "text", "text": ...}` or
        `{"type": "image", "data": <base64 str>, "mime_type": "image/jpeg",
        "resolution": "low"}`, in order: for each candidate, one text part
        with its metadata followed by one image part per peak frame; then
        the user prompt text part last.
    """
    parts: list[dict] = []
    for c in candidates:
        parts.append(
            {
                "type": "text",
                "text": (
                    f"id={c['id']} kind={c['kind']} src={c['src']} "
                    f"multi_subject={c['multi_subject']}"
                ),
            }
        )
        parts.extend(
            {
                "type": "image",
                "data": base64.b64encode(Path(jpg).read_bytes()).decode("ascii"),
                "mime_type": "image/jpeg",
                "resolution": "low",
            }
            for jpg in c["peak_frames"]
        )
    parts.append({"type": "text", "text": user_prompt})
    return parts


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
        attempts_usage.append(usage)
        cost = _cost_usd(usage, config["model"])
        total_cost += cost

        attempt_record = {
            "attempt": attempt,
            "status": interaction.status,
            "usage": usage,
            "cost_usd": cost,
        }
        if interaction.status != "incomplete":
            attempt_record["output"] = json.loads(interaction.output_text)
        with (session_dir / f"selection_attempt_{attempt}.json").open("w") as f:
            json.dump(attempt_record, f, indent=2, ensure_ascii=False)

        if interaction.status != "incomplete":
            selection = json.loads(interaction.output_text)
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
