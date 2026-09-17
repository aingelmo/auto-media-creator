"""Hook line generation: a separate LLM call after planning, #5.7.

Fed the operator's brief/audience, a text summary of the final EDL in
timeline order, and one low-res frame per other clip plus the chosen hook
candidate's 3 peak frames, so the model can ground the line in the whole
reel instead of just its first clip. Returns 3-5 lines, one per copy
device (pregunta/contraste/detalle/afirmacion/tu), each grounded in the
brief, the reel context, or the frames, with a verifiable
`{candidate_id, evidence, hooks}` contract.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests

from edl_agent.selection.s_checks import clean_hook_line, numbers_in
from edl_agent.selector.client import _usage_dict
from edl_agent.selector.pricing import _cost_usd, append_cost_entry
from edl_agent.selector.prompts import THEMES, build_parts

DEVICES: tuple[str, ...] = ("pregunta", "contraste", "detalle", "afirmacion", "tu")

AUDIENCE_TONE: dict[str, str] = {
    "members": "Audiencia: socios que ya entrenan aquí. Busca reconocimiento y "
    "cercanía (que se vean reflejados en la sesión), no venderles nada.",
    "prospects": "Audiencia: gente que aún no entrena aquí. Busca impacto y "
    "vender la sesión sin sonar a eslogan publicitario.",
}

HOOK_SYSTEM_PROMPT_TEMPLATE = """Eres copywriter de Reels para un gimnasio, \
escribiendo en español de España el texto que se sobreimprime en el primer \
segundo del vídeo, mientras se reproduce el clip gancho. Después de ese \
segundo se reproduce el resto del reel, clip a clip, en el orden que se te \
da. La frase debe preparar el reel entero, no solo describir el clip 1.

Recibes: un brief opcional del operador, la audiencia, el reel completo en \
su orden final (rol/ejercicio/duración/velocidad/motivo de cada clip, y el \
recuento real de clips), los 3 fotogramas del clip gancho (antes, pico, \
después), y 1 fotograma de cada uno de los demás clips, cada fotograma \
etiquetado con el id del clip al que pertenece. Velocidad = alturas de \
cuerpo por segundo en el pico; <0.7 es controlado, >1.2 es explosivo.

{audience_tone}

Antes de escribir, anota 2-3 hechos de evidencia visibles en TODOS los \
fotogramas (no solo el gancho): lugar, si es grupo o individual, material, \
o el contraste entre el primer clip y los siguientes.

Escribe entre 3 y 5 frases, cada una con un dispositivo distinto:
- pregunta: una pregunta corta sobre lo que se ve (¿...?).
- contraste: contrapone el clip gancho con lo que viene después.
- detalle: un objeto, lugar o recuento concreto y real del reel (no del \
gancho en solitario).
- afirmacion: una afirmación rotunda y defendible sobre el ejercicio o la \
sesión (hot take).
- tu: dirigida al espectador (tú/te), sin ser un eslogan.

Cada frase de 3 a 8 palabras. Deja una frase en "" si no puedes anclarla en \
el brief, el reel o los fotogramas -- mejor vacía que inventada. Cuanto más \
concreta y menos genérica, mejor: "Sesión de fuerza" no vale nada; nombrar \
algo que se ve en pantalla sí.

Regla de anclaje: toda frase debe apoyarse en el brief, el reel (incluido \
su recuento real de clips) o los fotogramas -- nunca menciones un objeto o \
ejercicio que no esté en el reel. Números solo si aparecen tal cual en el \
brief o coinciden con el recuento real de clips.

Prohibido en cualquier frase:
- repeticiones, kilos, récords, tiempos, resultados (salvo que vengan \
literales en el brief)
- emociones, dolor, lesión, competición
- eslóganes o clichés de marketing fitness ("sin excusas", "dalo todo", \
"a otro nivel", "modo bestia", "el límite", "transforma tu cuerpo", \
"quema grasa")
- comentarios sobre el cuerpo de los sujetos, emojis, hashtags, comillas, \
punto final

Ejemplos (con su dispositivo):
- contraste: sprint al inicio, resto en sala -> "De la calle a la sala"
- contraste: pico explosivo, resto controlado -> "Del empuje explosivo al front squat"
- detalle: 8 clips distintos de material variado -> "Suelo, pesas, máquinas: \
todo en un reel"
- afirmacion: varios clips en grupo -> "No entrenas solo aquí"
- pregunta: gancho de sled push -> "¿Quién empuja el trineo solo con brazos?"
- tu: reel con progresión clara -> "Aquí empiezas donde puedes seguir"

Tono (matiz, nunca eslogan): {hook_line}.

Responde únicamente con el JSON del schema, repitiendo candidate_id tal cual \
se recibe."""

HOOK_USER_TEMPLATE = """candidate_id={candidate_id} ejercicio={exercise} \
velocidad={speed:.2f} tema={theme} audiencia={audience}

brief={brief}

reel en orden:
{context}

Los fotogramas preceden a este mensaje: primero los 3 del clip gancho \
(id={candidate_id}), después 1 fotograma por cada uno de los demás clips, \
cada uno etiquetado con su id.

Describe la evidencia y escribe las frases gancho."""


def hook_copy_schema() -> dict:
    """Build the output schema for the hook-copy LLM call.

    Returns:
        JSON schema dict requiring `candidate_id`, `evidence` (0-3 strings)
        and `hooks` (3-5 items, each `{angle, hook_line}`, `angle` holding
        one of `DEVICES`).
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
                "maxItems": 5,
                "items": {
                    "type": "object",
                    "properties": {
                        "angle": {"type": "string", "enum": list(DEVICES)},
                        "hook_line": {
                            "type": "string",
                            "description": (
                                "3-8 palabras ancladas en el brief, el reel "
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
    others: list[dict] | None = None,
) -> dict:
    """Generate 3-5 device-tagged hook lines for `candidate`, per #5.7.

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
            people, partner WOD"); grounds the lines and allows its numbers.
        audience: `"prospects"` or `"members"`; only changes the system
            prompt's tone paragraph.
        context: Reel summary text (see `session.hooks.reel_context`),
            grounding all lines in the clips the viewer will actually see.
        others: Every other clip's candidate dict (see
            `candidates.build_video_candidates`), reads `id`, `kind`,
            `src`, `multi_subject`, `kp_speed_abs`, `peak_frames` (only the
            middle/peak frame is sent per candidate, to bound request
            size). `None`/`[]` if the hook candidate is the only clip.

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
    others_one_frame = [
        c | {"peak_frames": [c["peak_frames"][len(c["peak_frames"]) // 2]]}
        for c in (others or [])
    ]
    parts = build_parts([candidate, *others_one_frame], user_prompt)
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
                generation_config={"temperature": 0.7, "max_output_tokens": 768},
            )
            usage = _usage_dict(getattr(interaction, "usage", None))
            call_cost = _cost_usd(usage, model)
            cost += call_cost
            append_cost_entry(session_dir, "hooks", model, usage, call_cost)
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
    # `context` (session.hooks.reel_context) states the reel's real clip/
    # develop counts, e.g. "clips: 9 (develop: 7)"; those digits are true of
    # the reel, so a line naming them isn't an invented number.
    # ponytail: this also allows durations/speeds embedded in `context`
    # (e.g. "1.5s", "2.02") as a side effect of reusing numbers_in() on the
    # whole string; tighten with a dedicated regex over the counts line only
    # if a model starts citing invented-looking durations as hook numbers.
    allowed_numbers = numbers_in(brief) | numbers_in(context)
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
