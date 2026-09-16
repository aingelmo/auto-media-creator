"""Hook line generation: a separate LLM call after selection, #5.7.

Fed the chosen hook candidate's peak frames + exercise + speed + theme;
returns a single evidence-anchored line (or an abstention, `""`), with a
verifiable `{candidate_id, hook_line, evidence}` contract.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests

from edl_agent.selection.s_checks import clean_hook_line
from edl_agent.selector.client import _usage_dict
from edl_agent.selector.pricing import _cost_usd
from edl_agent.selector.prompts import THEMES, build_parts

HOOK_SYSTEM_PROMPT_TEMPLATE = """Eres un observador que describe en español de \
España lo que ve en un fotograma de un Reel de gimnasio, para sobreimprimir \
en el primer segundo del vídeo.

Recibes los 3 fotogramas del momento gancho (antes, pico, después), el \
ejercicio, la velocidad real del sujeto en el pico (alturas de cuerpo por \
segundo; <0.7 es controlado, >1.2 es explosivo) y la temática.

Primero identifica la evidencia: hechos visibles en los fotogramas (objeto, \
fase del movimiento, posición del cuerpo). Nada inferido, nada que no se vea.

Luego escribe una frase de 3 a 6 palabras que describa SOLO esa evidencia.

Prohibido en la frase:
- repeticiones, kilos, récords, tiempos, resultados
- emociones, dolor, competición, día de la semana, intención
- segunda persona (tú/te), exclamaciones, emojis, hashtags, comillas, punto final
- lenguaje motivacional/eslogan ("sin excusas", "dalo todo", "a otro nivel", \
"modo bestia", "el límite")

Ejemplos anclados a evidencia:
- deadlift, barra despegando del suelo -> "la barra despega del suelo"
- clean and jerk, barra arriba -> "la barra termina arriba"
- box jump, atleta en el aire -> "salto por encima del cajón"
- sin evidencia clara -> hook_line: ""

Tono (matiz, nunca eslogan): {hook_line}.

Responde únicamente con el JSON del schema, repitiendo candidate_id tal cual \
se recibe."""

HOOK_USER_TEMPLATE = """candidate_id={candidate_id} ejercicio={exercise} \
velocidad={speed:.2f} tema={theme}

Los 3 fotogramas (antes, pico, después) preceden a este mensaje.

Describe la evidencia y, si es posible, la frase gancho."""


def hook_copy_schema() -> dict:
    """Build the output schema for the hook-copy LLM call.

    Returns:
        JSON schema dict requiring `candidate_id`, `evidence` (0-3 strings)
        and `hook_line`.
    """
    return {
        "type": "object",
        "properties": {
            "candidate_id": {"type": "string"},
            "evidence": {
                "type": "array",
                "minItems": 0,
                "maxItems": 3,
                "items": {
                    "type": "string",
                    "description": (
                        "Hechos visibles en los fotogramas: objeto, fase del "
                        "movimiento, posición del cuerpo; nada inferido."
                    ),
                },
            },
            "hook_line": {
                "type": "string",
                "description": (
                    "3-6 palabras que describen solo un hecho de evidence; "
                    "cadena vacía si evidence no permite una frase concreta."
                ),
            },
        },
        "required": ["candidate_id", "evidence", "hook_line"],
    }


def build_hook_system_prompt(theme: str = "training") -> str:
    """Fill in `HOOK_SYSTEM_PROMPT_TEMPLATE` with the theme's tone, per #5.7."""
    return HOOK_SYSTEM_PROMPT_TEMPLATE.format(hook_line=THEMES[theme]["hook_line"])


def build_hook_user_prompt(
    candidate_id: str, exercise: str, speed: float, theme: str = "training"
) -> str:
    """Fill in `HOOK_USER_TEMPLATE` with the hook candidate's metadata, per #5.7."""
    return HOOK_USER_TEMPLATE.format(
        candidate_id=candidate_id, exercise=exercise, speed=speed, theme=theme
    )


def generate_hook_copy(
    candidate: dict,
    exercise: str,
    theme: str,
    client: Any,  # noqa: ANN401 (duck-typed: google-genai Client or OllamaClient)
    model: str,
    session_dir: Path,
    hook_line_override: str = "",
) -> dict:
    """Generate one evidence-anchored hook line for `candidate`, per #5.7.

    Args:
        candidate: The hook-role candidate dict (see
            `selector.admissible_candidates`); reads `id`, `peak_frames`,
            `kp_speed_abs`.
        exercise: Canonical exercise name of the hook candidate.
        theme: Key of `selector.prompts.THEMES`.
        client: A `google.genai.Client`-shaped object, as built by
            `edl_agent.llm.get_client`.
        model: Model name to call.
        session_dir: Session directory to write `hooks.json` to.
        hook_line_override: Operator-typed text; if non-empty, skips the LLM
            call entirely.

    Returns:
        `{"candidate_id", "hook_line", "evidence", "rejected", "source",
        "usage", "cost_usd", "system_prompt", "user_prompt", "raw"}`.
        `rejected` is `None` for a clean line or a legitimate abstention,
        else one of `"candidate_id_mismatch"`, `"invalid_copy"`,
        `"no_evidence"`. Also written to `session_dir/hooks.json`.
    """
    session_dir = Path(session_dir)

    if hook_line_override:
        result = {
            "candidate_id": candidate["id"],
            "hook_line": hook_line_override,
            "evidence": [],
            "rejected": None,
            "source": "override",
            "usage": None,
            "cost_usd": 0.0,
            "system_prompt": "",
            "user_prompt": "",
            "raw": {},
        }
        with (session_dir / "hooks.json").open("w") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        return result

    speed = candidate.get("kp_speed_abs", 0.0)
    user_prompt = build_hook_user_prompt(candidate["id"], exercise, speed, theme)
    parts = build_parts([candidate], user_prompt)
    system_prompt = build_hook_system_prompt(theme)

    usage = None
    cost = 0.0
    raw: dict = {}
    for _attempt in range(2):
        try:
            interaction = client.interactions.create(
                model=model,
                system_instruction=system_prompt,
                input=parts,
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": hook_copy_schema(),
                },
                generation_config={"temperature": 0.2, "max_output_tokens": 512},
            )
            usage = _usage_dict(getattr(interaction, "usage", None))
            cost += _cost_usd(usage, model)
            if interaction.status == "incomplete":
                raw = {}
                continue
            raw = json.loads(interaction.output_text)
            break
        except (requests.RequestException, json.JSONDecodeError):
            raw = {}
            continue

    evidence = [str(e) for e in raw.get("evidence", []) if str(e).strip()]
    hook_line = ""
    rejected: str | None = None

    if raw.get("candidate_id") != candidate["id"]:
        rejected = "candidate_id_mismatch"
    else:
        cleaned = clean_hook_line(raw.get("hook_line"), strict=True)
        raw_line = str(raw.get("hook_line") or "").strip()
        if cleaned == "" and raw_line != "":
            rejected = "invalid_copy"
        elif cleaned and not evidence:
            rejected = "no_evidence"
            cleaned = ""
        hook_line = cleaned

    result = {
        "candidate_id": candidate["id"],
        "hook_line": hook_line,
        "evidence": evidence,
        "rejected": rejected,
        "source": "llm",
        "usage": usage,
        "cost_usd": cost,
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "raw": raw,
    }
    with (session_dir / "hooks.json").open("w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    return result
