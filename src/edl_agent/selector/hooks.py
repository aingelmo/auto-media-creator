"""Hook line generation: a separate LLM call after selection, #5.7.

Fed the chosen hook candidate's peak frames + exercise + speed + theme;
returns 6 lines, one per forced angle, for the operator to pick from in the
web UI (or line #1 for the CLI).
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

HOOK_ANGLES: list[tuple[str, str]] = [
    ("reto", "reta al espectador, segunda persona (tú/te)"),
    ("pregunta", "pregunta directa sobre lo que se ve o sobre el espectador"),
    ("momento", "describe literalmente lo que está pasando en el fotograma"),
    ("comunidad", 'voz de insider del gimnasio, tipo "el WOD de hoy…"'),
    ("contraste", "expectativa vs realidad, o un antes/después"),
    ("confesion", "punto de vista en primera persona, confesión relatable"),
]

HOOK_SYSTEM_PROMPT_TEMPLATE = """Eres copywriter de Reels de gimnasio para \
redes en España.

Recibes los 3 fotogramas del momento gancho de un Reel (antes, pico, \
después), el ejercicio, la velocidad real del sujeto en el pico (alturas de \
cuerpo por segundo; <0.7 es controlado, >1.2 es explosivo) y la temática.

Escribe una frase gancho por cada ángulo pedido, para sobreimprimir en el \
primer segundo del vídeo.

Reglas:
- Tuteo, coloquial, minúsculas (sin mayúscula inicial salvo nombres propios).
- Frase corta: 3-7 palabras.
- Sin emojis, sin hashtags, sin comillas.
- Sin nombre del gimnasio ni de la ciudad.
- Sin cifras inventadas: nada de repeticiones, kilos ni tiempos.
- La intensidad debe respetar la velocidad: <0.7 controlado, >1.2 explosivo.
- Debe referirse a lo que se ve (ejercicio, material, momento), no un \
eslogan genérico.
- Tono: {hook_line}.
- Las 6 líneas deben ser todas distintas entre sí.
- Responde únicamente con el JSON del schema."""

HOOK_USER_TEMPLATE = """ejercicio={exercise} velocidad={speed:.2f} tema={theme}

Los 3 fotogramas (antes, pico, después) preceden a este mensaje.

Genera una línea por cada ángulo."""

REINFORCED_SUFFIX = "\n\nCada línea: máximo 6 palabras."


def hooks_schema() -> dict:
    """Build the output schema for the hooks LLM call.

    Returns:
        JSON schema dict requiring `lines`, a 6-item array of
        `{angle, text}` (`angle` restricted to `HOOK_ANGLES`' keys).
    """
    angle_keys = [key for key, _ in HOOK_ANGLES]
    return {
        "type": "object",
        "properties": {
            "lines": {
                "type": "array",
                "minItems": 6,
                "maxItems": 6,
                "items": {
                    "type": "object",
                    "properties": {
                        "angle": {"type": "string", "enum": angle_keys},
                        "text": {
                            "type": "string",
                            "description": (
                                "Frase gancho en español, 3-7 palabras, "
                                "minúsculas, sin emojis ni comillas."
                            ),
                        },
                    },
                    "required": ["angle", "text"],
                },
            },
        },
        "required": ["lines"],
    }


def build_hook_system_prompt(theme: str = "training") -> str:
    """Fill in `HOOK_SYSTEM_PROMPT_TEMPLATE` with the theme's tone, per #5.7."""
    return HOOK_SYSTEM_PROMPT_TEMPLATE.format(hook_line=THEMES[theme]["hook_line"])


def build_hook_user_prompt(
    exercise: str, speed: float, theme: str = "training"
) -> str:
    """Fill in `HOOK_USER_TEMPLATE` with the hook candidate's metadata, per #5.7."""
    return HOOK_USER_TEMPLATE.format(exercise=exercise, speed=speed, theme=theme)


def generate_hooks(
    candidate: dict,
    exercise: str,
    theme: str,
    client: Any,  # noqa: ANN401 (duck-typed: google-genai Client or OllamaClient)
    model: str,
    session_dir: Path,
) -> dict:
    """Generate 6 hook lines (one per `HOOK_ANGLES` entry) for `candidate`, per #5.7.

    Args:
        candidate: The hook-role candidate dict (see
            `selector.admissible_candidates`); reads `peak_frames`,
            `kp_speed_abs`.
        exercise: Canonical exercise name of the hook candidate.
        theme: Key of `selector.prompts.THEMES`.
        client: A `google.genai.Client`-shaped object, as built by
            `edl_agent.llm.get_client`.
        model: Model name to call.
        session_dir: Session directory to write `hooks.json` to.

    Returns:
        `{"candidate_id", "lines": [{"angle", "text"}], "usage",
        "cost_usd", "system_prompt", "user_prompt", "raw"}`. `lines` has
        as many entries as survived cleaning/deduping (0-6); if fewer than
        3 survive the first attempt, one retry is made with a reinforced
        suffix. Also written to `session_dir/hooks.json`.
    """
    session_dir = Path(session_dir)
    speed = candidate.get("kp_speed_abs", 0.0)
    user_prompt = build_hook_user_prompt(exercise, speed, theme)
    parts = build_parts([candidate], user_prompt)
    base_system_prompt = build_hook_system_prompt(theme)

    lines: list[dict] = []
    usage = None
    cost = 0.0
    raw: dict = {}
    system_prompt = base_system_prompt
    for _attempt in range(2):
        try:
            interaction = client.interactions.create(
                model=model,
                system_instruction=system_prompt,
                input=parts,
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": hooks_schema(),
                },
                generation_config={"temperature": 0.7, "max_output_tokens": 4096},
            )
            usage = _usage_dict(getattr(interaction, "usage", None))
            cost += _cost_usd(usage, model)
            raw = (
                json.loads(interaction.output_text)
                if interaction.status != "incomplete"
                else {}
            )
        except (requests.RequestException, json.JSONDecodeError):
            raw = {}

        seen_texts: set[str] = set()
        lines = []
        for item in raw.get("lines", []):
            text = clean_hook_line(item.get("text"))
            if not text or text in seen_texts:
                continue
            seen_texts.add(text)
            lines.append({"angle": item.get("angle", ""), "text": text})

        if len(lines) >= 3:
            break
        system_prompt = base_system_prompt + REINFORCED_SUFFIX

    result = {
        "candidate_id": candidate["id"],
        "lines": lines,
        "usage": usage,
        "cost_usd": cost,
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "raw": raw,
    }
    with (session_dir / "hooks.json").open("w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    return result
