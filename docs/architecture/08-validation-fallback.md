[← README](README.md)

## 8. Capa 5 — Validación, asserts y fallback

### 8.1 Checks sobre `selection.json` (S)

| # | Check | Acción |
|---|---|---|
| S1 | JSON parseable y cumple schema (solo puede fallar por `status: incomplete`) | LLM (máx. 2) |
| S2 | Todos los `candidate_id` existen, son admisibles y no se repiten entre `selected`/`rejected` | código: descartar inexistentes/duplicados |
| S3 | `rank` por rol sin huecos ni repetidos | código: renumerar por orden de aparición |
| S4 | `hook` solo `kind == peak`; `close` solo `calm/image` | código: mover el candidato a `develop` (si `kind == peak`) o a `close` (si `calm/image` estaba en hook) |
| S5 | ≥ 1 candidato admisible para `hook`, ≥ 1 para `close`, ≥ 1 para `develop` (si hay slots develop) | rol: fallback parcial del rol que falte |

`exercise` ya no se comprueba: el `enum` del schema lo garantiza.

### 8.2 Invariantes del planner (asserts; fallo = error de sesión, nunca reparación)

| # | Invariante |
|---|---|
| P1 | `len(clips) == N_SLOTS`, un clip por slot, slots en orden |
| P2 | `candidate_id` único en `clips` |
| P3 | `window[0] ≤ in_s` y `out_s ≤ window[1]` (vídeo) |
| P4 | `0 ≤ in_s < out_s ≤ duration_s` de la fuente (vídeo) |
| P5 | `round((out_s − in_s − n_ramp/30·ramp_speed) * 30) + n_ramp == n_frames` (`n_ramp = 0` salvo `effect == ramp`) |
| P6 | `timeline_start_f[i+1] == timeline_end_f[i]`, `timeline_start_f[0] == 0`, `timeline_end_f[-1] == duration_f`, `Σ n_frames == duration_f` |
| P7 | Sin solapes de la misma fuente (margen 0.25 s) |
| P8 | `crop` en `[0,1]`; `crop_px` dentro de `W×H`, `w,h` pares, y `|w_px/h_px − 9/16| · h_px ≤ 2 px` si `layout == crop` |
| P9 | `n_frames ≥ 30` por clip |

Estos invariantes se cubren con property tests sobre candidatos sintéticos (§14) y se evalúan en producción como asserts. Las restricciones que sí pueden no cumplirse por falta de material (variedad de ejercicio, `src` adyacente, cuotas por rol) se resuelven **dentro** de la búsqueda del planner con blacklist y relajación (§6.2), no en un bucle de reparación posterior.

### 8.3 Warnings (no bloquean; obligan a revisión humana del preview)

| # | Condición | Warning |
|---|---|---|
| W1 | Nº de clips con `subject_cropped` > 3 o con `upscale_gt_1.3` > 3 | `low_framing_quality` |
| W2 | `Σ` de `relaxed_4/relaxed_5` > N_SLOTS/2 | `low_material_quality` |
| W3 | `arc_fallback` o `peak_off_beat` en ≥ 2 clips | `weak_rhythm` |
| W4 | Hook con `effect == ramp` y `round(src_fps_nominal) ≤ 30` (30.003 de iPhone cuenta como 30) | `slowmo_duplicates` |
| W5 | `sharpness` es relativa al clip: si el fallback de hook elige por `sharpness` entre clips distintos | `sharpness_cross_clip` (informativo) |

### 8.4 Checks de render (R) — ver §10.5

### 8.5 Flujo

```text
selection.json
   ├─ S1 falla ──► reintento LLM (máx. 2) ──► sigue fallando ──► fallback total de reglas
   ├─ S2-S4 fallan ──► reparación en código
   ├─ S5 falla para un rol ──► fallback parcial SOLO de ese rol (se conservan los demás roles del LLM)
   ▼
planner (con relajación interna) → edl.json
   ├─ P1-P9 fallan ──► ERROR de sesión (bug del planner; se guarda todo para reproducir)
   ├─ W1-W5 ──► warnings en provenance
   ▼
preview por segmento (siempre) → render → R1-R6 → reel.mp4
```

`provenance.planner`: `llm` si ningún rol vino del fallback; `mixed` si alguno; `rules_fallback` si todos. `fallback_roles` lista cuáles.

### 8.6 Fallback de reglas (0 €, por rol)

- **hook:** candidato `peak` admisible con mayor `kp_speed`, `motion_bg ≤ 0.4`, `sharpness ≥ 0.5`, `multi_subject == false` si hay alguno así.
- **close:** candidato `calm` con mayor `sharpness · centralidad`; si no hay `calm`, imagen; si no hay imagen, el `peak` con menor `kp_speed` y `warning: close_not_calm`.
- **develop:** candidatos `peak` ordenados por `score_cv`, repartidos por fuente en round-robin para variedad; se aplica exactamente el mismo planner (6.2–6.6) con `exercise = "unknown"` para todos (la regla de no repetir ejercicio se desactiva; la de `src` adyacente se mantiene).
- El fallback nunca reutiliza un `candidate_id` ya asignado por el LLM en otro rol.


