[← README](README.md)

## 14. Plan de pruebas y orden de implementación

Todas las sesiones se guardan enteras (`sessions/<id>/`) y forman el set de regresión. Cambiar modelo, prompt, umbrales, cadena de tonemap o `render_profile` obliga a re-ejecutar las sesiones 1–7 y comparar EDLs.

**Orden de implementación (cada paso cierra con su prueba):**

1. **Ingesta + proxy + verificación temporal (§3, §4.4).** Clips: HLG vertical, DV 8.4 horizontal, `start_time ≠ 0` (fabricar con `ffmpeg -itsoffset 1.5 -i x.mov -c copy y.mov`), 60 fps, 25 fps. Cierra: los 5 instantes alinean a ±0 frames en todos.
2. **Render + concat + audio desde una EDL escrita a mano (§10)**, sin CV ni LLM, con hook a `speed=0.5` sobre fuente 30 y 60 fps. Cierra: R1–R6 en verde; `nb_read_frames` por segmento; `normalization_type: linear`; re-render con la misma EDL da el mismo sha256 de `reel.mp4`.
3. **Slots + planner con candidatos sintéticos (§4.1, §6).** Cierra: property tests de P1–P9, `beats_per_slot` correcto para 60/90/128/175 bpm, pico sobre beat, arco de develop, `crop_px` dentro de `W×H` en fuentes 16:9, 4:3, 9:16, 9:19.5 y 1:1.
4. **Features + candidatos sobre clips reales (§4.2–4.3).** Cierra: inspección de hojas de contacto: ≥ 80 % de los `peak` son acción del atleta, no de cámara `[validar]`; ≥ 2 `calm` por sesión de gimnasio típica.
5. **Fallback de reglas end-to-end (Sesiones 1–3).** Métricas: nº candidatos (meta 20–40), nº `calm` (≥ 2), slots relajados, warnings W1–W5. Si el fallback ya produce un Reel publicable, es el suelo de calidad.
6. **Selector LLM (Sesiones 4–7).** Dos reels por sesión (LLM vs fallback), evaluación a ciegas del dueño del gimnasio; tokens y coste real por llamada; `thinking_level` low vs medium; 3.7 vs 3.8 Flash; un set con ≥ 2 personas; otro con ≤ 6 candidatos válidos.
7. **Casos límite forzados (Sesiones 8–10).** Todo horizontal; música > 140 BPM; pista ambiental sin beats; sesión solo con fotos; clip de 2.5 s; sesión sin música. Criterio: el pipeline termina, emite los warnings esperados de §12 y la EDL valida.
8. **Regresión:** `make regress` re-planifica las 10 sesiones desde `selection.json` guardado (sin LLM), hace diff de EDL y re-renderiza una comprobando sha256 del reel; `make regress-llm` rehace la selección y reporta cambios de `candidate_id` por rol.

