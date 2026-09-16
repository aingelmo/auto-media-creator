"""Hook line generation: a separate LLM call after selection, #5.7.

Fed the operator's brief/audience, a text summary of the whole selection,
and the chosen hook candidate's peak frames + exercise + speed; returns 3
lines (one per fixed angle: contexto/afirmacion/adelanto), each grounded in
the brief, the selection summary, or the frames, with a verifiable
`{candidate_id, evidence, hooks}` contract.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests

from edl_agent.selection.s_checks import clean_hook_line, numbers_in
from edl_agent.selector.client import _usage_dict
from edl_agent.selector.pricing import _cost_usd
from edl_agent.selector.prompts import THEMES, build_parts

ANGLES: tuple[str, ...] = ("contexto", "afirmacion", "adelanto")

AUDIENCE_TONE: dict[str, str] = {
    "members": "Audiencia: socios que ya entrenan aquí. Busca reconocimiento y "
    "cercanía (que se vean reflejados en la sesión), no venderles nada.",
    "prospects": "Audiencia: gente que aún no entrena aquí. Busca impacto y "
    "vender la sesión sin sonar a eslogan publicitario.",
}

HOOK_SYSTEM_PROMPT_TEMPLATE = """Eres copywriter de Reels para un gimnasio, \
escribiendo en español de España el texto que se sobreimprime en el primer \
segundo del vídeo.

Recibes: un brief opcional del operador, la audiencia, un resumen de la \
selección de clips del reel (roles, ejercicios, duración, notas), y los 3 \
fotogramas del momento gancho (antes, pico, después) con su ejercicio y \
velocidad real del sujeto en el pico (alturas de cuerpo por segundo; <0.7 es \
controlado, >1.2 es explosivo).

{audience_tone}

Escribe exactamente 3 frases, una por cada ángulo:
- contexto: qué es este reel (sesión/clase/día/lugar); usa el brief o el \
resumen si los dan esa información, si no describe la sesión en general.
- afirmacion: una afirmación rotunda y defendible sobre el ejercicio o la \
sesión (hot take), anclada en lo que se ve o en el resumen.
- adelanto: lo que el espectador está a punto de ver (contraste o \
progresión entre los clips seleccionados).

Cada frase de 3 a 6 palabras. Deja una frase en "" si no puedes anclarla en \
el brief, el resumen o los fotogramas -- mejor vacía que inventada.

Regla de anclaje: toda frase debe apoyarse en el brief, el resumen de la \
selección o los fotogramas. Números solo si aparecen tal cual en el brief.

Prohibido en cualquier frase:
- repeticiones, kilos, récords, tiempos, resultados (salvo que vengan \
literales en el brief)
- emociones, dolor, competición, intención
- segunda persona (tú/te), preguntas, exclamaciones, emojis, hashtags, \
comillas, punto final
- lenguaje motivacional/eslogan ("sin excusas", "dalo todo", "a otro nivel", \
"modo bestia", "el límite")

Ejemplos:
- contexto: brief "Clase de Hyrox del jueves" -> "El jueves de Hyrox"
- contexto: sin brief, tema training -> "Entreno de fuerza funcional"
- afirmacion: wall ball en el resumen -> "El wall ball se hace con piernas"
- afirmacion: sesión con varias estaciones -> "Cada estación cuenta el doble"
- adelanto: resumen con 5 clips de desarrollo -> "Cinco estaciones sin descanso"
- adelanto: deadlift, barra despegando del suelo -> "la barra despega del suelo"

Tono (matiz, nunca eslogan): {hook_line}.

Responde únicamente con el JSON del schema, repitiendo candidate_id tal cual \
se recibe."""

HOOK_USER_TEMPLATE = """candidate_id={candidate_id} ejercicio={exercise} \
velocidad={speed:.2f} tema={theme} audiencia={audience}

brief={brief}

resumen de la selección:
{context}

Los 3 fotogramas (antes, pico, después) preceden a este mensaje.

Describe la evidencia y escribe las 3 frases gancho."""


def hook_copy_schema() -> dict:
    """Build the output schema for the hook-copy LLM call.

    Returns:
        JSON schema dict requiring `candidate_id`, `evidence` (0-3 strings)
        and `hooks` (3 items, each `{angle, hook_line}`).
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
            "hooks": {
                "type": "array",
                "minItems": 3,
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "properties": {
                        "angle": {"type": "string", "enum": list(ANGLES)},
                        "hook_line": {
                            "type": "string",
                            "description": (
                                "3-6 palabras ancladas en el brief, el resumen "
                                "o los fotogramas; cadena vacía si no se puede "
                                "anclar."
                            ),
                        },
                    },
                    "required": ["angle", "hook_line"],
                },
            },
        },
        "required": ["candidate_id", "evidence", "hooks"],
    }


def build_hook_system_prompt(
    theme: str = "training", audience: str = "prospects"
) -> str:
    """Fill in `HOOK_SYSTEM_PROMPT_TEMPLATE` with the theme/audience tone, per #5.7."""
    return HOOK_SYSTEM_PROMPT_TEMPLATE.format(
        hook_line=THEMES[theme]["hook_line"],
        audience_tone=AUDIENCE_TONE.get(audience, AUDIENCE_TONE["prospects"]),
    )


def build_hook_user_prompt(
    candidate_id: str,
    exercise: str,
    speed: float,
    theme: str = "training",
    brief: str = "",
    audience: str = "prospects",
    context: str = "",
) -> str:
    """Fill in `HOOK_USER_TEMPLATE` with the hook candidate's metadata, per #5.7."""
    return HOOK_USER_TEMPLATE.format(
        candidate_id=candidate_id,
        exercise=exercise,
        speed=speed,
        theme=theme,
        audience=audience,
        brief=brief or "(sin brief)",
        context=context or "(sin resumen)",
    )


def generate_hook_copy(
    candidate: dict,
    exercise: str,
    theme: str,
    client: Any,  # noqa: ANN401 (duck-typed: google-genai Client or OllamaClient)
    model: str,
    session_dir: Path,
    hook_line_override: str = "",
    brief: str = "",
    audience: str = "prospects",
    context: str = "",
) -> dict:
    """Generate 3 angle-anchored hook lines for `candidate`, per #5.7.

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
        brief: Operator-typed session brief (e.g. "Hyrox class, Thursday, 12
            people, partner WOD"); grounds `contexto` and allows its numbers.
        audience: `"prospects"` or `"members"`; only changes the system
            prompt's tone paragraph.
        context: Selection summary text (see
            `session.hooks.selection_context`), grounding all 3 angles.

    Returns:
        `{"candidate_id", "hook_line", "hooks", "dropped", "evidence",
        "rejected", "source", "usage", "cost_usd", "system_prompt",
        "user_prompt", "raw", "brief", "audience", "context"}`.
        `hook_line` is `hooks[0]["hook_line"]` or `""`, kept for the
        planner/CLI contract. `rejected` is `None` for at least one
        surviving line, else one of `"candidate_id_mismatch"`,
        `"invalid_copy"`. Also written to `session_dir/hooks.json`.
    """
    session_dir = Path(session_dir)

    if hook_line_override:
        result = {
            "candidate_id": candidate["id"],
            "hook_line": hook_line_override,
            "hooks": [{"angle": "", "hook_line": hook_line_override}],
            "dropped": [],
            "evidence": [],
            "rejected": None,
            "source": "override",
            "usage": None,
            "cost_usd": 0.0,
            "system_prompt": "",
            "user_prompt": "",
            "raw": {},
            "brief": brief,
            "audience": audience,
            "context": context,
        }
        with (session_dir / "hooks.json").open("w") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        return result

    speed = candidate.get("kp_speed_abs", 0.0)
    user_prompt = build_hook_user_prompt(
        candidate["id"], exercise, speed, theme, brief, audience, context
    )
    parts = build_parts([candidate], user_prompt)
    system_prompt = build_hook_system_prompt(theme, audience)

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
                generation_config={"temperature": 0.7, "max_output_tokens": 512},
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
    raw_hooks = raw.get("hooks", [])
    allowed_numbers = numbers_in(brief)
    hooks: list[dict] = []
    dropped: list[dict] = []
    rejected: str | None = None

    if raw.get("candidate_id") != candidate["id"]:
        rejected = "candidate_id_mismatch"
    else:
        for entry in raw_hooks:
            angle = str(entry.get("angle", ""))
            raw_line = str(entry.get("hook_line") or "").strip()
            cleaned = clean_hook_line(
                entry.get("hook_line"), strict=True, allowed_numbers=allowed_numbers
            )
            if cleaned:
                hooks.append({"angle": angle, "hook_line": cleaned})
            elif raw_line:
                dropped.append(
                    {"angle": angle, "hook_line": raw_line, "why": "invalid_copy"}
                )
        if not hooks and raw_hooks:
            rejected = "invalid_copy"

    result = {
        "candidate_id": candidate["id"],
        "hook_line": hooks[0]["hook_line"] if hooks else "",
        "hooks": hooks,
        "dropped": dropped,
        "evidence": evidence,
        "rejected": rejected,
        "source": "llm",
        "usage": usage,
        "cost_usd": cost,
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "raw": raw,
        "brief": brief,
        "audience": audience,
        "context": context,
    }
    with (session_dir / "hooks.json").open("w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    return result
