"""Capa 3 - Selector LLM (Gemini), #5.

Construye la peticion inline-image (#5.1) a partir de los candidatos admisibles
de candidates.json, la envia con la Interactions API de google-genai y aplica
los reintentos por `status: "incomplete"` (#5.6). Guarda cada intento como
`selection_attempt_N.json` en session_dir. El resultado (`selection`,
`selection_meta`) se pasa directo a `session.run_planner`.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

DEFAULTS = {
    "model": "gemini-3.7-flash",
    "thinking_level": "low",
    "thinking_level_many_candidates": "medium",  # #5.1: >=30 candidatos
    "many_candidates_threshold": 30,
    "temperature": 0.2,
    "max_output_tokens": 16384,
    "max_attempts": 2,  # #5.6
}

# Lista canonica de ejercicios, #5.5.
EXERCISES = [
    "back squat", "front squat", "overhead squat", "deadlift", "clean", "snatch",
    "jerk", "thruster", "pull-up", "muscle-up", "push-up", "burpee", "box jump",
    "wall ball", "kettlebell swing", "rowing", "bike", "ski erg", "run",
    "rope climb", "handstand", "double-under", "other",
]

SYSTEM_PROMPT = """Eres un editor de vídeo profesional especializado en Reels verticales (9:16) de gimnasio.

Recibes una lista de MOMENTOS CANDIDATOS. Cada candidato tiene un id, un tipo (peak = momento de acción, calm = momento estable, image = foto) y uno o tres fotogramas: justo antes del pico, el pico y justo después. Recibes también los SLOTS del montaje con su rol narrativo y una LISTA CANÓNICA DE EJERCICIOS.

Tu tarea es juzgar contenido, no calcular tiempos, coordenadas ni orden temporal.

1. RECHAZA los candidatos con: desenfoque en el fotograma central, sujeto fuera de encuadre o tapado, encuadre que no permite ver la ejecución, o contenido idéntico a otro candidato mejor del mismo clip.
2. SELECCIONA todos los demás y asigna a cada uno UN rol:
   - hook: máxima explosividad o impacto visual. Solo tipo peak.
   - close: sujeto estable, centrado, final limpio. Solo tipo calm o image.
   - develop: el resto. Prioriza variedad de ejercicios y planos donde se ve bien la técnica.
3. Asigna rank dentro de cada rol: 1 = mejor calidad. Sin huecos (1, 2, 3, …). El orden en el montaje lo decide otro sistema.
4. exercise: usa exactamente un nombre de la lista canónica; si no encaja, "other".
5. Si hay menos de 3 candidatos válidos para develop o ninguno para hook o close, explícalo en notes. No inventes candidatos ni fuerces rechazos para cumplir cuotas.

Reglas:
- Usa solo candidate_id existentes. No emitas tiempos ni coordenadas.
- reason: máximo 12 palabras. Responde únicamente con el JSON del schema."""

REINFORCED_SUFFIX = "\n\nreason: máximo 8 palabras."

# #11: USD por 1M tokens, vigente hasta 31/12/2026 (misma tarifa 3.7/3.8-flash).
# Los tokens de thinking se facturan como salida.
PRICING_PER_MTOK = {"gemini-3.7-flash": (0.75, 3.75), "gemini-3.8-flash": (0.75, 3.75)}


def _cost_usd(usage: dict | None, model: str) -> float:
    if usage is None or model not in PRICING_PER_MTOK:
        return 0.0
    input_price, output_price = PRICING_PER_MTOK[model]
    input_tokens = usage.get("total_input_tokens", 0) or 0
    output_tokens = (usage.get("total_output_tokens", 0) or 0) + (usage.get("total_thought_tokens", 0) or 0)
    return input_tokens * input_price / 1e6 + output_tokens * output_price / 1e6

USER_PROMPT_TEMPLATE = """OBJETIVO: Reel de {duration_s} s. Temática: resumen dinámico de entrenamiento.

SLOTS (N_SLOTS = {n_slots}): 1 hook, {n_develop} develop, 1 close.

LISTA CANÓNICA DE EJERCICIOS:
{exercises}

CANDIDATOS: {n_cand} (ids: {ids}). Los fotogramas de cada uno preceden a este mensaje, etiquetados con su id.

Genera la selección."""


def selection_schema() -> dict:
    """#5.3: schema de salida, structured output de Gemini."""
    return {
        "type": "object",
        "properties": {
            "selected": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "candidate_id": {"type": "string"},
                        "role": {"type": "string", "enum": ["hook", "develop", "close"]},
                        "rank": {"type": "integer", "minimum": 1,
                                 "description": "Calidad dentro de su rol. 1 = mejor. Sin huecos. No es orden temporal."},
                        "exercise": {"type": "string", "enum": EXERCISES},
                        "reason": {"type": "string", "description": "Máximo 12 palabras."},
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
                        "reason": {"type": "string", "description": "Máximo 8 palabras."},
                    },
                    "required": ["candidate_id", "reason"],
                },
            },
            "notes": {"type": "string",
                       "description": "Vacío salvo problemas globales (pocos candidatos válidos, todo el material repetido, etc.)."},
        },
        "required": ["selected", "rejected", "notes"],
    }


def admissible_candidates(candidates_json: dict, slots_json: dict) -> list[dict]:
    """#5.1: solo candidatos que caben en al menos un slot se envian al LLM."""
    slot_indices = {s["slot"] for s in slots_json["slots"]}
    return [c for c in candidates_json["candidates"] if set(c["admits_slots"]) & slot_indices]


def build_user_prompt(duration_s: float, slots_json: dict, candidates: list[dict]) -> str:
    slots = slots_json["slots"]
    n_develop = sum(1 for s in slots if s["role"] == "develop")
    return USER_PROMPT_TEMPLATE.format(
        duration_s=duration_s, n_slots=len(slots), n_develop=n_develop,
        exercises=", ".join(EXERCISES), n_cand=len(candidates),
        ids=", ".join(c["id"] for c in candidates),
    )


def build_parts(candidates: list[dict], user_prompt: str) -> list[dict]:
    """#5.1: partes text+image (base64, resolution low) por candidato + prompt de usuario."""
    parts: list[dict] = []
    for c in candidates:
        parts.append({
            "type": "text",
            "text": f"id={c['id']} kind={c['kind']} src={c['src']} multi_subject={c['multi_subject']}",
        })
        for jpg in c["peak_frames"]:
            parts.append({
                "type": "image",
                "data": base64.b64encode(Path(jpg).read_bytes()).decode("ascii"),
                "mime_type": "image/jpeg",
                "resolution": "low",
            })
    parts.append({"type": "text", "text": user_prompt})
    return parts


def _usage_dict(usage) -> dict | None:
    if usage is None:
        return None
    return usage.model_dump() if hasattr(usage, "model_dump") else dict(usage)


def _sdk_version() -> str | None:
    try:
        from google import genai
        return genai.__version__
    except ImportError:
        return None


def select(
    candidates_json: dict, slots_json: dict, duration_s: float, client,
    session_dir: Path, config: dict | None = None,
) -> tuple[dict | None, dict]:
    """#5.1+#5.6: llama al selector LLM con reintentos, guarda cada intento
    y devuelve (selection, selection_meta) para `session.run_planner`.
    `selection` es `None` si se agotan los reintentos sin un intento completo
    (queda todo el rol en manos del fallback de reglas, #8.6).
    """
    config = {**DEFAULTS, **(config or {})}
    session_dir = Path(session_dir)

    candidates = admissible_candidates(candidates_json, slots_json)
    user_prompt = build_user_prompt(duration_s, slots_json, candidates)
    parts = build_parts(candidates, user_prompt)
    thinking_level = (
        config["thinking_level_many_candidates"] if len(candidates) >= config["many_candidates_threshold"]
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
            response_format={"type": "text", "mime_type": "application/json", "schema": selection_schema()},
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

        attempt_record = {"attempt": attempt, "status": interaction.status, "usage": usage, "cost_usd": cost}
        if interaction.status != "incomplete":
            attempt_record["output"] = json.loads(interaction.output_text)
        with open(session_dir / f"selection_attempt_{attempt}.json", "w") as f:
            json.dump(attempt_record, f, indent=2, ensure_ascii=False)

        if interaction.status != "incomplete":
            selection = json.loads(interaction.output_text)
            break
        system_prompt = SYSTEM_PROMPT + REINFORCED_SUFFIX  # #5.6: reintento reforzado

    meta = {
        "model": config["model"],
        "sdk_version": _sdk_version(),
        "api_revision": None,  # [validar] no expuesto por el SDK de alto nivel
        "llm_attempts": len(attempts_usage),
        "llm_usage": attempts_usage[-1] if attempts_usage else None,
        "llm_cost_usd": total_cost,
    }
    return selection, meta
