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

Antes de escribir, anota 2-3 hechos de evidencia que se vean sin lugar a \
dudas en los fotogramas: qué hace el cuerpo, en qué fase del movimiento \
está, diferencia de ritmo entre el gancho y el resto. Describe solo lo que \
se ve; si no distingues bien algo, no lo anotes. No fuerces un fallo \
técnico: la mayoría de los clips son de gente entrenando correctamente y \
no hay nada que juzgar.

Los fotogramas sirven para confirmar CÓMO se mueve el cuerpo, nunca para \
bautizar un objeto o un ejercicio nuevo. Solo puedes nombrar un objeto o \
un ejercicio si aparece en el campo `ejercicio` de algún clip o en el \
brief: si crees ver una kettlebell, una banda, una cuña o una sentadilla \
frontal y no está en los datos del reel, para ti no existe y no puede \
aparecer ni en la evidencia ni en las frases.

Escribe entre 3 y 5 frases, cada una con un dispositivo distinto. Ninguna \
debe ser un eslogan ni una descripción plana.

Regla que vale para todas: el sujeto de la frase es siempre una persona o \
lo que hace. El suelo, la colchoneta, el cajón, la acera, la sala, el \
apoyo o el material nunca son el protagonista ni pueden regir el verbo \
("La colchoneta te va a durar", "El suelo no perdona", "A ti el suelo te \
va a pesar", "Te toca aguantar el cajón" son frases inválidas: el mobiliario \
no hace nada). Habla de gente entrenando, no del decorado.
- pregunta: solo si en el fotograma se ve un fallo técnico inequívoco y \
verificable (algo que cualquiera señalaría al mirar la imagen). Si no lo \
hay, deja "" -- nunca inventes una duda del tipo "¿eso cuenta?" sobre un \
gesto correcto o que no distingues. Que un movimiento aparezca a medias o \
sin terminar en el fotograma NO es un fallo técnico: el clip dura un \
segundo y corta donde corta. Nunca preguntes si algo "cuenta", "vale" o \
"es trampa" por estar incompleto en imagen -- en ese caso deja "".
- contraste: enfrenta los dos momentos más distintos del reel. NO tienes \
que usar el clip `close`: el close es casi siempre el clip más tranquilo \
del reel, y rematar ahí deja la frase sin fuerza ("acabas subido al \
cajón", "acaba apoyado en la columna", "acabas sentado"). Elige el clip \
del reel que de verdad se oponga al gancho -- el más duro, el más lento o \
el más cargado. Las dos mitades tienen que nombrar algo que hace una \
persona (correr, remar, empujar, colgarse, saltar): un sitio o una postura \
("del suelo", "empiezas tumbado", "en la sala") no vale como mitad. Si las \
dos mitades se parecen ("del suelo al suelo") o no sabes qué pasa en el \
otro clip, deja "". Prohibido el molde "Empieza(s) X y acaba(s) Y" y sus \
variantes con "arranca"/"sales": si tu frase encaja en él, reescríbela con \
otra forma.
- detalle: un detalle visible y lo que delata, las dos cosas en la misma \
frase. Si la frase se puede leer como pie de foto del fotograma ("Manos al \
suelo junto a la mancuerna", "Cadera hacia atrás, rodillas flexionadas", \
"Brazos y piernas levantados a la vez", "Todo el grupo tumbado en el \
suelo"), no vale: falta lo que ese detalle significa para el que entrena.
- afirmacion: una regla que un entrenador diría de verdad en voz alta \
durante ese ejercicio, y que seguiría siendo cierta fuera de este vídeo. \
Si suena a aforismo fabricado a medida para el fotograma ("Sin zancada no \
hay carrera que valga", "Si el torso se despega, pierde", "El suelo se \
entrena desde abajo"), no vale: deja "". Sin juzgar si un gesto "vale" o \
"cuenta" salvo que el fallo sea evidente.
- tu: interpela directamente al espectador (tú/te) sobre lo que tendría \
que hacer, o sobre lo que notaría, si se metiera en ese momento del reel. \
No prometas sufrimiento ni anuncies qué músculo le va a arder o vaciar \
salvo que el movimiento lo cargue de forma evidente (un trineo cargado, \
colgarse de la barra); si el gesto es suave o no sabes cómo se ejecuta, \
deja "". Nunca señales "el último", "la última", "el final" o "el último \
tramo" como la parte dura: el reel termina en el clip más tranquilo, así \
que esa promesa siempre sale falsa.

Cada frase de 3 a 8 palabras, y cuanto más corta mejor: si la primera \
mitad se sostiene sola, borra la segunda ("Correr se entrena" es mejor que \
"Correr se entrena, no se sale a trotar"). Prefiere la palabra evocadora a \
la literal: "al aire libre" antes que "en la acera" o "en la calle". Deja \
una frase en "" si no puedes anclarla en el brief, el reel o los \
fotogramas -- mejor vacía que inventada; es normal devolver solo 3 frases \
útiles.

Regla de anclaje: toda frase debe apoyarse en el brief, el reel o los \
fotogramas -- nunca menciones un objeto o ejercicio que no esté en el reel.

Nombres de ejercicio: usa exclusivamente el nombre que se te da en el \
campo `ejercicio` de cada clip (tradúcelo al español si hace falta: run = \
carrera, push-up = flexión, sled push = empuje de trineo). Si el ejercicio \
es `other` o no se te da, no bautices el movimiento: habla de lo que hace \
el cuerpo (tira, empuja, sostiene, se levanta) sin ponerle nombre, o deja \
la frase en "". Nunca inventes \
un nombre de ejercicio ni describas un gesto como si fuera un ejercicio \
("cadera en flexión", "zancada del gancho", "pico de espalda" no existen).

Prohibido en cualquier frase:
- cualquier cifra interna del reel: velocidad, duraciones, número de \
clips, ids de clip. Esas cifras son evidencia para ti, el espectador no \
las ve ni las entiende. Números solo si aparecen tal cual en el brief
- repeticiones, kilos, récords, tiempos, resultados (salvo que vengan \
literales en el brief)
- emociones, dolor, lesión, competición
- eslóganes o clichés de marketing fitness ("sin excusas", "dalo todo", \
"a otro nivel", "modo bestia", "el límite", "transforma tu cuerpo", \
"quema grasa")
- comentarios sobre el cuerpo de los sujetos, emojis, hashtags, comillas, \
punto final

Los ejemplos de abajo son de otros reels: cada uno usa una estructura de \
frase distinta a propósito. Copia esa variedad, nunca el texto ni la \
evidencia -- una frase de los ejemplos repetida tal cual en tu respuesta \
es un error, aunque encaje. Si la frase se pudiera rellenar con dos huecos \
para cualquier otro reel, no es lo bastante punzante: reescríbela con las \
palabras propias de estos clips.

Ejemplos de formato (evidencia -> frase).
- pregunta: rodilla claramente hundida hacia dentro en el pico -> "¿Ves \
hacia dónde va esa rodilla?"
- contraste: gancho corriendo fuera, otro clip remando -> "Corriendo al \
aire libre, remando al final"
- contraste: gancho con trineo, otro clip colgado de la barra -> "Del \
trineo a la barra sin respirar"
- contraste: gancho saltando al cajón, otro clip empujando disco -> \
"Saltas al cajón, luego arrastras el disco"
- detalle: nadie apoya los talones en la sentadilla -> "Ni un talón toca \
el suelo"
- afirmacion: remo en máquina con tirón claro de piernas -> "El remo se \
tira con las piernas"
- tu: dominadas estrictas en el reel -> "Tú te descuelgas en la tercera"

Ejemplos de frases inválidas (no las imites ni por forma ni por fondo).
- "Esa colchoneta te va a durar" -> el decorado no es el protagonista
- "Cadera hacia atrás, rodillas flexionadas" -> pie de foto, no dice nada
- "Te va a costar llegar a la última" -> el reel acaba en el clip más suave
- "Del suelo al suelo, sin despegar la mancuerna" -> no hay contraste
- "Corren con la kettlebell pegada al pecho" -> objeto que no está en el reel

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
                                "o los fotogramas, sin cifras internas del reel "
                                "(velocidad, duración, número de clips); cadena "
                                "vacía si no se puede anclar."
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
    # Only the operator's brief licenses a number. `context` digits (speeds,
    # durations, clip counts) are internal metrics the viewer never sees --
    # allowing them let lines like "Arranca a 1.60" or "¿Cuántos de los 9
    # clips aguantas?" through review.
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
