[← README](README.md)

## 12. Casos límite y comportamiento esperado

| Caso | Comportamiento v4 |
|---|---|
| Varias personas en plano | tracker multi-persona; sujeto = mayor `Σ kp_speed·área`; `multi_subject` visible para el LLM; warning en EDL |
| Cámara en mano con temblor | `motion_bg` alto no descalifica `peak` salvo > 0.6 en el pico; descalifica `calm`; los picos se detectan por `kp_speed`, no por movimiento global |
| Clip más corto que el slot | no admitido para ese slot (6.1); no se envía al LLM si no admite ninguno; borde 0.25 s en clips < 5 s |
| Pocos candidatos | relajación 5.1–5.5, luego fallback parcial de `develop`; `warning: few_candidates` |
| Dos clips del mismo plano seguidos | prohibido por defecto; relajación 5.2 lo permite con gap ≥ 1 s y `warning: relaxed_2` |
| Todo horizontal | crop 9:16 + `upscale_gt_1.3` → `blur_pad` automático; preview obligatoria |
| Música sin beats claros | `beats_confident = false` → grid uniforme de 48 frames con beats sintéticos cada 24 |
| Música muy rápida (> 120 BPM) | `beats_per_slot ≥ 3`, slots ≥ 30 frames garantizados |
| Solo 2 slots posibles | sin `develop`; el prompt lo refleja |
| Imagen como hook | permitido solo si no hay ningún `peak` válido (relajación 5.5); Ken Burns opcional |
| Solo imágenes en la sesión | pipeline válido: todos los slots con `kind: image`, `warning: images_only` |
| `start_time_s ≠ 0` | irrelevante por convención de tiempo; detectado por §4.4 si algo falla |
| Fuente ya 9:16 pero 1080p | crop identidad, sin upscale (1080→1080) |
| Fuente 60 fps con hook a 0.5 | slow-motion real (frames únicos); fuente 30 fps → duplicados + `warning: slowmo_duplicates` |
| Fuente DV 8.4 | tratada como HLG; RPU ignorado; con libplacebo, `apply_dolbyvision=false` `[validar visualmente]` |
| Fuente 10 bits sin `color_transfer` | error de ingesta (no se asume SDR) |
| Truncado del LLM (`status: incomplete`) | reintento con `reason` acortado; luego fallback total |
| Selección con `hook` de tipo `calm` | S4 lo mueve a `close`; si no queda hook → fallback parcial de hook |
| loudnorm cae a dinámico | R5: warning y aceptar, o error según config |
| Sin música (derechos) | `music_cut_path = null`, render con `-an`, sin loudnorm |


