[← README](README.md)

## 5. Capa 3 — Selector (LLM)

### 5.1 Modo por defecto: imágenes de pico inline

- Entrada: por cada candidato **admisible**, sus `peak_frames` como partes `image` inline (base64) con `resolution: "low"`, precedidas de una parte `text` con `id`, `kind`, `src`, `multi_subject`. Después, el prompt de usuario con slots y la lista canónica de ejercicios.
- Coste: 280 tokens/imagen en `low` (560 `medium`, 1120 `high`/default) para modelos Gemini 3 `[verificado: docs media-resolution]`. 30 candidatos × 3 imágenes ≈ 25k tokens. Sin `resolution` explícita serían ≈ 101k.
- `thinking_level`: `low` por defecto; `medium` si hay ≥ 30 candidatos.
- `max_output_tokens = 16384`: el límite incluye los tokens de thinking y, si se agota, la interacción termina con `status: "incomplete"` y salida truncada o vacía, facturando el thinking `[verificado: docs thinking]`. 4096 era insuficiente.
- Petición (Python, google-genai; nombres de parámetros `[verificado: docs Interactions API]`):

```python
parts = []
for c in admissible_candidates:
    parts.append({"type": "text", "text": f"id={c['id']} kind={c['kind']} src={c['src']} multi_subject={c['multi_subject']}"})
    for jpg in c["peak_frames"]:
        parts.append({"type": "image", "data": b64(jpg), "mime_type": "image/jpeg", "resolution": "low"})  # [validar] nombre del campo para inline (data vs uri)
parts.append({"type": "text", "text": USER_PROMPT})

interaction = client.interactions.create(
    model=GEMINI_MODEL,
    system_instruction=SYSTEM_PROMPT,
    input=parts,
    response_format={"type": "text", "mime_type": "application/json", "schema": SELECTION_SCHEMA},
    generation_config={"thinking_level": "low", "temperature": 0.2, "max_output_tokens": 16384},
)
if interaction.status == "incomplete":
    ...  # reintento (§5.6)
selection = json.loads(interaction.output_text)
```

Se registran `google-genai.__version__` y el `Api-Revision` efectivo en `provenance`. La versión del SDK va fijada en `requirements.txt`.

### 5.2 Modo opcional: ventanas de vídeo

Solo si en las pruebas las imágenes no bastan para juzgar "movimiento de cámara no intencionado" o ejecución del ejercicio. Por candidato se recorta `[t_min, t_max]` del proxy a un MP4 sin audio y se envía inline (< 20 MB por petición) o vía Files API (retención 48 h, reutilizable en reintentos). En este modo el prompt debe dar `t_peak` en tiempo local del recorte (`t_peak − t_min`). Muestreo estático a 2 fps `[validar nombre exacto del parámetro processing en Interactions API]`.

Nota de coste: en vídeo cada frame cuesta 70 tokens en `low`/`medium` `[verificado: docs media-resolution]`. Una ventana de 4 s a 2 fps son 8 frames = 560 tokens, **menos** que 3 imágenes en `low` (840). El modo vídeo no es el caro; el modo imágenes se mantiene por simplicidad de implementación, no por coste.

### 5.3 Schema de salida — `selection.json`

Compatible con structured output de Gemini (sin `$schema`, sin `const`, sin `default`, sin `exclusiveMinimum`; `enum` admitido en string, number e integer; `minItems/maxItems`, `minimum/maximum` admitidos `[verificado: docs structured-output]`). `EXERCISES` es la lista canónica de §5.5 más `"other"`, y se inyecta como `enum`, lo que garantiza el valor y elimina un check.

```json
{
  "type": "object",
  "properties": {
    "selected": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "candidate_id": { "type": "string" },
          "role": { "type": "string", "enum": ["hook", "develop", "close"] },
          "rank": { "type": "integer", "minimum": 1, "description": "Calidad dentro de su rol. 1 = mejor. Sin huecos. No es orden temporal." },
          "exercise": { "type": "string", "enum": ["__EXERCISES__"] },
          "reason": { "type": "string", "description": "Máximo 12 palabras." }
        },
        "required": ["candidate_id", "role", "rank", "exercise", "reason"]
      }
    },
    "rejected": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "candidate_id": { "type": "string" },
          "reason": { "type": "string", "description": "Máximo 8 palabras." }
        },
        "required": ["candidate_id", "reason"]
      }
    },
    "notes": { "type": "string", "description": "Vacío salvo problemas globales (pocos candidatos válidos, todo el material repetido, etc.)." }
  },
  "required": ["selected", "rejected", "notes"]
}
```

### 5.4 System prompt

Las líneas `hook`/`close` y la `Temática:` del user prompt dependen de `config["theme"]` (`"training"` por defecto, cubre CrossFit/Hyrox/funcional; `"yoga"`). Se muestra la variante `training`; la de `yoga` pide como hook «la postura o transición más impactante visualmente (inversión, equilibrio, apertura amplia). Solo tipo peak.» y como close «postura de reposo o meditación (savasana, sentado, manos en el pecho), sujeto centrado y quieto. Prioriza tipo calm o image; …» con el mismo fallback a peak. La invariante hook=peak se mantiene en ambos temas.

```text
Eres un editor de vídeo profesional especializado en Reels verticales (9:16) de gimnasio.

Recibes una lista de MOMENTOS CANDIDATOS. Cada candidato tiene un id, un tipo (peak = momento de acción, calm = momento estable, image = foto) y uno o tres fotogramas: justo antes del pico, el pico y justo después. Recibes también los SLOTS del montaje con su rol narrativo y una LISTA CANÓNICA DE EJERCICIOS.

Tu tarea es juzgar contenido, no calcular tiempos, coordenadas ni orden temporal.

1. RECHAZA los candidatos con: desenfoque en el fotograma central, sujeto fuera de encuadre o tapado, encuadre que no permite ver la ejecución, o contenido idéntico a otro candidato mejor del mismo clip.
2. SELECCIONA todos los demás y asigna a cada uno UN rol:
   - hook: máxima explosividad o impacto visual. Solo tipo peak.
   - close: sujeto estable, centrado, final limpio. Prioriza tipo calm o image; si no hay ninguno disponible, usa el candidato peak que se vea más quieto (menos movimiento, pose más estática) y dilo en notes.
   - develop: el resto. Prioriza variedad de ejercicios y planos donde se ve bien la técnica.
3. Asigna rank dentro de cada rol: 1 = mejor calidad. Sin huecos (1, 2, 3, …). El orden en el montaje lo decide otro sistema.
4. exercise: usa exactamente un nombre de la lista canónica; si no encaja, "other".
5. Si hay menos de 3 candidatos válidos para develop o ninguno para hook o close, explícalo en notes. No inventes candidatos ni fuerces rechazos para cumplir cuotas.

Reglas:
- Usa solo candidate_id existentes. No emitas tiempos ni coordenadas.
- reason: máximo 12 palabras, describe solo lo visible; no nombres un ejercicio específico salvo que sea exactamente el de "exercise" (si "exercise" es "other", no inventes un nombre de ejercicio en reason).
- Responde únicamente con el JSON del schema.
```

### 5.5 User prompt (dinámico)

```text
OBJETIVO: Reel de {duration_s} s. Temática: resumen dinámico de entrenamiento (CrossFit, Hyrox, funcional).

SLOTS (N_SLOTS = {n}): 1 hook, {n-2} develop, 1 close.

LISTA CANÓNICA DE EJERCICIOS:
back squat, front squat, overhead squat, deadlift, clean, snatch, jerk, thruster, pull-up, muscle-up, push-up, burpee, box jump, wall ball, kettlebell swing, rowing, bike, ski erg, run, rope climb, handstand, double-under, sled push, sled pull, farmers carry, sandbag lunge, lunge, toes-to-bar, sun salutation, warrior pose, downward dog, balance pose, inversion, backbend, stretch, savasana, other

CANDIDATOS: {n_cand} (ids: {ids}). Los fotogramas de cada uno preceden a este mensaje, etiquetados con su id.

Genera la selección.
```

Se adjunta a cada candidato solo `id`, `kind`, `src`, `multi_subject`; no se pasan `kp_speed`/`sharpness` (sesgan al modelo hacia lo que ya sabe el código) ni duraciones de slot (el modelo no decide tiempos). Los candidatos no admisibles no se envían.

### 5.6 Validación sintáctica y reintentos

- El schema forzado hace que el JSON sea válido salvo truncado (`status == "incomplete"`). Si ocurre → reintento con `thinking_level: low` y prompt reforzado "reason ≤ 8 palabras".
- Máximo 2 reintentos al LLM en total por sesión, y solo por `status: incomplete`. El resto se repara en código o con fallback **parcial**.
- Cada intento se guarda como `selection_attempt_N.json` con `usage` (tokens de entrada, salida y thinking), `status` y coste calculado.

### 5.7 Hook lines — `hooks.json`

Ya no hay un único `hook_line` dentro de `selection.json`. La llamada de hook-copy corre **después del planner**, no antes: el planner primero construye el EDL con `hook_line_override=""` (§6), y esa EDL ya ordenada es lo que alimenta la llamada de hooks (mismo proveedor/modelo), que devuelve 3-5 líneas, cada una con un dispositivo de copy distinto, con contrato verificable: `{candidate_id, evidence, hooks: [{angle, hook_line}]}` (`hook_copy_schema` en `selector/hooks.py`; `angle` guarda el nombre del dispositivo, no un ángulo fijo). El planner corre una segunda vez con la línea elegida para producir el EDL final.

Este orden importa: generar los hooks antes de planificar solo daba al LLM la lista de candidatos del selector (rankeada, sin recortar a duración), no los clips que el planner realmente coloca en el reel — de ahí líneas que prometían un trineo o un kettlebell que no aparecían en el reel final.

Input: un brief opcional del operador (`str`, libre) y la audiencia (`"prospects"` | `"members"`, elegidos por sesión); un resumen en texto del EDL final en su orden de reproducción (`session/hooks.py: reel_context` — rol/ejercicio/duración/velocidad/motivo de cada clip *ya colocado*, el recuento real de clips y de develop, y las notas del selector); los 3 fotogramas de pico del candidato hook con su ejercicio y velocidad; y 1 fotograma (el central) de cada uno de los demás clips del reel, cada imagen etiquetada con el id de su clip, para que el modelo pueda anclar la línea en el reel entero y no solo en el primer clip.

Dispositivos de copy (3-5 líneas, uno por dispositivo, sin ángulo fijo):
- `pregunta` — pregunta corta sobre lo que se ve.
- `contraste` — contrapone el clip gancho con lo que viene después.
- `detalle` — un objeto, lugar o recuento concreto y real del reel.
- `afirmacion` — afirmación rotunda y defendible sobre el ejercicio o la sesión (hot take).
- `tu` — dirigida al espectador (tú/te), sin ser eslogan.

La audiencia solo cambia el párrafo de tono del prompt; el tema mantiene su matiz existente vía `THEMES[theme]["hook_line"]`. Regla de anclaje: toda frase debe apoyarse en el brief, el reel (incluido su recuento real de clips) o los fotogramas — nunca un objeto/ejercicio ausente del reel; los números solo se permiten si aparecen literales en el brief o en el resumen del reel (`numbers_in`/`allowed_numbers` en `clean_hook_line`, unión de ambos textos). Preguntas y segunda persona (tú/te) están permitidas — ya no prohibidas. Prohíbe explícitamente reps/kilos/tiempos/récords inventados, dolor/lesión, comentarios sobre el cuerpo, exclamaciones, emojis, hashtags, comillas, punto final y lenguaje motivacional/eslogan (incluye "transforma tu cuerpo", "quema grasa"). Cadena vacía en cualquier `hook_line` que no se pueda anclar (abstención legítima). Temperatura 0.7, hasta 8 palabras por línea (antes 6).

Validación en código (`generate_hook_copy`, `selector/hooks.py`):
- `candidate_id` de la respuesta distinto del candidato hook real → todas las líneas se descartan, `rejected: "candidate_id_mismatch"`.
- Cada `hooks[i].hook_line` pasa por `clean_hook_line(line, strict=True, allowed_numbers=...)` (`selection/s_checks.py`); las líneas inválidas se descartan y se listan en `dropped: [{angle, hook_line, why}]`.
- `hooks` en el resultado = las líneas que sobreviven; `hook_line` (compatibilidad con el CLI/planner) = `hooks[0]["hook_line"]` o `""`.
- `rejected: "invalid_copy"` solo si el modelo devolvió ≥1 línea y ninguna sobrevivió.
- Un solo reintento, solo por `status: "incomplete"` o error de red/JSON; nunca por abstención.

Si el operador ya escribió texto (`hook_line_override`, desde el formulario de alta o de regenerar), se salta la llamada LLM por completo: `hooks.json` se escribe con `source: "override"`, `evidence: []`, `cost_usd: 0.0`.

El operador ve las líneas (con su dispositivo) renderizadas sobre el hook, más una variante sin texto, en la pausa `hook_choice` de la web UI, y puede aceptar una, escribir texto propio, o elegir "sin texto"; "Regenerate" pide un lote nuevo. El CLI usa `hooks.json["hook_line"]` sin pausa. `hooks.json` también guarda `brief`, `audience` y `context` (el resumen del reel enviado), para depuración.

