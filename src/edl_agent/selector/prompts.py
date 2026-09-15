"""System/user prompt text and structured-output schema, #5.1+#5.3."""

from __future__ import annotations

import base64
from pathlib import Path

from edl_agent.selector._common import EXERCISES

SYSTEM_PROMPT_TEMPLATE = """Eres un editor de vídeo profesional especializado en Reels \
verticales (9:16) de gimnasio.

Recibes una lista de MOMENTOS CANDIDATOS. Cada candidato tiene un id, un tipo \
(peak = momento de acción, calm = momento estable, image = foto) y uno o tres \
fotogramas: justo antes del pico, el pico y justo después. Cada candidato \
lleva además velocidad=N: velocidad real del sujeto en el pico (alturas de \
cuerpo por segundo, comparable entre candidatos). Los fotogramas no distinguen \
un movimiento lento de uno explosivo; fíate de velocidad para eso: <0.7 es \
lento o controlado, >1.2 es explosivo (salto, sprint, burpee). Recibes también \
los SLOTS del montaje con su rol narrativo y una LISTA CANÓNICA DE EJERCICIOS.

Tu tarea es juzgar contenido, no calcular tiempos, coordenadas ni orden temporal.

1. RECHAZA los candidatos con: desenfoque en el fotograma central, sujeto fuera \
de encuadre o tapado, encuadre que no permite ver la ejecución, o contenido \
idéntico a otro candidato mejor del mismo clip.
2. SELECCIONA todos los demás y asigna a cada uno UN rol:
   - hook: {hook}
   - close: {close}
   - develop: el resto. Prioriza variedad de ejercicios y planos donde se ve \
bien la técnica.
3. Asigna rank dentro de cada rol: 1 = mejor calidad. Sin huecos (1, 2, 3, …). \
El orden en el montaje lo decide otro sistema.
4. exercise: usa exactamente un nombre de la lista canónica; si no encaja, "other".
5. Si hay menos de 3 candidatos válidos para develop o ninguno para hook o close, \
explícalo en notes. No inventes candidatos ni fuerces rechazos para cumplir cuotas.

Reglas:
- Usa solo candidate_id existentes. No emitas tiempos ni coordenadas.
- reason: máximo 12 palabras, describe solo lo visible; no nombres un \
ejercicio específico salvo que sea exactamente el de "exercise" (si \
"exercise" es "other", no inventes un nombre de ejercicio en reason).
- Responde únicamente con el JSON del schema."""

REINFORCED_SUFFIX = "\n\nreason: máximo 8 palabras."

_CLOSE_FALLBACK = (
    "si no hay ninguno disponible, usa el candidato peak que se vea más "
    "quieto (menos movimiento, pose más estática) y dilo en notes."
)

# Theme-dependent prompt lines; the rest of the prompt is shared.
THEMES: dict[str, dict[str, str]] = {
    "training": {
        "tematica": "resumen dinámico de entrenamiento (CrossFit, Hyrox, funcional).",
        "hook": "máxima explosividad o impacto visual. Solo tipo peak.",
        "close": "sujeto estable, centrado, final limpio. Prioriza tipo calm o "
        "image; " + _CLOSE_FALLBACK,
        "hook_line": "enérgico, directo",
    },
    "yoga": {
        "tematica": "flujo de yoga sereno: posturas limpias, transiciones "
        "fluidas, ambiente calmado.",
        "hook": "la postura o transición más impactante visualmente "
        "(inversión, equilibrio, apertura amplia). Solo tipo peak.",
        "close": "postura de reposo o meditación (savasana, sentado, manos en "
        "el pecho), sujeto centrado y quieto. Prioriza tipo calm o image; "
        + _CLOSE_FALLBACK,
        "hook_line": "sereno, sin exclamaciones",
    },
}

USER_PROMPT_TEMPLATE = """OBJETIVO: Reel de {duration_s} s. Temática: {tematica}

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


def build_system_prompt(theme: str = "training") -> str:
    """Fill in `SYSTEM_PROMPT_TEMPLATE` with the theme's hook/close guidance.

    Args:
        theme: Key of `THEMES` (`"training"` or `"yoga"`).

    Returns:
        System prompt text (in Spanish).
    """
    t = THEMES[theme]
    return SYSTEM_PROMPT_TEMPLATE.format(hook=t["hook"], close=t["close"])


def build_user_prompt(
    duration_s: float,
    slots_json: dict,
    candidates: list[dict],
    theme: str = "training",
) -> str:
    """Fill in `USER_PROMPT_TEMPLATE` with the current session, per #5.1.

    Args:
        duration_s: Target reel duration, in seconds.
        slots_json: Parsed `slots.json`, with a `slots` key.
        candidates: Admissible candidates (see `admissible_candidates`);
            only their `id`s are used here.
        theme: Key of `THEMES`; picks the `Temática:` line.

    Returns:
        Filled-in user prompt text (in Spanish, matching `build_system_prompt`).
    """
    slots = slots_json["slots"]
    n_develop = sum(1 for s in slots if s["role"] == "develop")
    return USER_PROMPT_TEMPLATE.format(
        duration_s=duration_s,
        tematica=THEMES[theme]["tematica"],
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
            Reads `id`, `kind`, `src`, `multi_subject`, `kp_speed_abs`
            (optional, defaults to 0.0), `peak_frames`
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
                    f"multi_subject={c['multi_subject']} "
                    f"velocidad={c.get('kp_speed_abs', 0.0):.2f}"
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
