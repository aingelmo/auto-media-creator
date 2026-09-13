# Arquitectura del Sistema de Montaje Automatizado (EDL Agent) — v4

Cambios respecto a v3 (resumen): orden de filtros `setpts→fps` corregido en render (C1); pista musical recortada una sola vez a WAV y usada en beats y en render (C2); `resolution: low` explícita por imagen y coste recalculado con 280 tok/imagen (C3); `peak`/`calm` basados en velocidad de keypoints y movimiento de fondo, no en diferencia global de frame (A1); `max_output_tokens` ampliado y comprobación de `status` (A2); checks nuevos de render (segmento↔preview por pHash, frames por segmento, `normalization_type`, DTS monótono) y eliminación de `-shortest` (A3); EDL con `render_profile`, versiones, hilos, crop en píxeles y parámetros de efectos (A4); fórmula de `beats_per_slot` corregida (M1); pico alineado a beat en vez de `lead=0.35` (M2); colocación de develop en arco (M3); `exercise` como `enum` y filtrado de candidatos no admisibles antes del LLM (M4); invariantes del planner como asserts, no como reparaciones (M5); verificación temporal proxy↔original en máximos de movimiento con test de vecinos (M6); Ken Burns sobre fuente pre-escalada (M7); relajación coherente (M8); constraint "no misma fuente en slots adyacentes"; `boxblur` y orden de `scale` optimizados; modelo por defecto parametrizado a `gemini-3.7-flash`.

Todo lo marcado `[validar]` requiere confirmación con material real antes de darlo por cerrado. Lo marcado `[verificado]` se ha contrastado con documentación y no requiere validación.

---

## 0. Principio de diseño

- **El LLM decide *qué*:** qué candidatos son buenos, en qué papel narrativo (hook, develop, close) y con qué calidad relativa dentro de cada papel.
- **El código decide *cuándo* y *dónde*:** frames exactos de corte, alineación a beats, orden de los develop, crop y duración total.
- **Consecuencia:** el LLM nunca emite tiempos, píxeles ni orden temporal. Solo emite `candidate_id`, `role`, `rank`, `exercise`, `reason`. Todo lo numérico lo construye código determinista y se valida contra un schema.
- **Reproducibilidad:** cada artefacto (`manifest`, `candidates`, `selection`, `edl`) lleva hash de sus entradas. La EDL es autocontenida: incluye versiones de herramientas, número de hilos, perfil de render y todos los parámetros de efectos, de modo que una sesión guardada re-renderice bit a bit meses después sin acceso a nada que no esté en `edl.json` + ficheros fuente.
- **Los invariantes del planner son asserts, no reparaciones.** Si un invariante falla, es un bug del planner y la sesión se detiene con error; no se parchea la EDL a posteriori.

---

## Índice

Cada sección numerada de la spec vive en su propio fichero; los números de
sección (`#4.3`, `§10.5`, ...) citados en el código y en esta documentación
se corresponden 1:1 con el prefijo del fichero.

| Fichero | Sección | Contenido |
|---|---|---|
| [01-conventions.md](01-conventions.md) | §1 | Convenciones globales (target, unidades de tiempo, layout de sesión) |
| [02-layer-diagram.md](02-layer-diagram.md) | §2 | Diagrama de las 7 capas del pipeline |
| [03-ingest.md](03-ingest.md) | §3 | Capa 1 — Ingesta: `manifest.json`, proxies, imágenes, pista musical |
| [04-features.md](04-features.md) | §4 | Capa 2 — Features locales: audio→slots, vídeo→series, candidatos, verificación proxy↔original |
| [05-selector-llm.md](05-selector-llm.md) | §5 | Capa 3 — Selector LLM: prompts, schema de `selection.json`, coste, reintentos |
| [06-planner.md](06-planner.md) | §6 | Capa 4 — Planner determinista: admisión, asignación, timing, crop, efectos |
| [07-edl-contract.md](07-edl-contract.md) | §7 | Contrato `edl.json` (JSON Schema completo) |
| [08-validation-fallback.md](08-validation-fallback.md) | §8 | Capa 5 — Validación: checks S/P/W, fallback de reglas |
| [09-preview.md](09-preview.md) | §9 | Capa 6 — Preview por segmento |
| [10-render.md](10-render.md) | §10 | Capa 7 — Render: comandos FFmpeg, concat, audio, checks R |
| [11-model-cost.md](11-model-cost.md) | §11 | Modelo LLM y coste por Reel |
| [12-edge-cases.md](12-edge-cases.md) | §12 | Casos límite y comportamiento esperado |
| [13-open-risks.md](13-open-risks.md) | §13 | Riesgos abiertos / pendientes de validar |
| [14-test-plan.md](14-test-plan.md) | §14 | Plan de pruebas y orden de implementación |
