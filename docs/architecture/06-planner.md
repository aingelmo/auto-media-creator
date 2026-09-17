[← README](README.md)

## 6. Capa 4 — Planner determinista (snapper)

Todo en frames de 30 fps. Notación: `d_f` = duración del slot en frames; `speed` = 1.0 siempre (campo conservado por compatibilidad). El hook lleva una **rampa de velocidad** (§6.3) en vez de un `speed` plano.

### 6.1 Admisión de un candidato en un slot

```python
need_s = d_f / 30 * speed
admits = (window[1] - window[0]) >= need_s + 2/30     # margen de 2 frames
```

Un candidato no admitido para un slot no se considera para ese slot (no se clampa a la fuerza). Es el mismo cálculo que produce `admits_slots` en §4.3.

### 6.2 Asignación

1. **hook:** candidato con `role == hook` y menor `rank` que admita `d_f`. Si no hay → fallback parcial de rol (Capa 5).
2. **close:** ídem con `role == close`. Solo `kind ∈ {calm, image}`.
3. **develop — selección:** se recorre la lista `role == develop` por `rank` y se toman los primeros `k = N_SLOTS − 2` que cumplan, respecto a los ya tomados:
   - admiten la duración de al menos un slot develop libre;
   - `exercise` distinto al del anterior tomado (comparación exacta tras `lower().strip()`; `other` cuenta como distinto de todo excepto de `other`);
   - `src` distinta a la del anterior tomado (evita jump cuts del mismo plano);
   - no solapan `[in_s, out_s]` con ningún segmento ya usado de la misma fuente (margen 0.25 s);
   - `candidate_id` no usado todavía.
4. **develop — colocación en arco:** los `k` tomados, ordenados por `rank` como `r1 (mejor) … rk`, se colocan en los slots develop `s1 … sk` así: `s1 = r2, s2 = r4, s3 = r6, …` y, tras agotar los pares, los impares en orden descendente terminando en `sk = r1`. El mejor develop queda justo antes del close. Tras colocar se re-verifican las restricciones de adyacencia (ejercicio y `src` entre slots consecutivos, incluyendo hook y close); si alguna falla, se intercambian pares adyacentes hasta 3 veces; si sigue fallando, se colocan en orden de `rank` y se registra `warning: arc_fallback`.
5. **Relajación** si faltan candidatos, en este orden y registrando `warning: relaxed_N` en el clip:
   1. permitir repetir ejercicio;
   2. permitir misma `src` en slots adyacentes (con gap ≥ 1 s entre `out_s` del anterior e `in_s` del siguiente);
   3. usar cualquier candidato **seleccionado** de otro rol (hook o close sobrantes), por `rank`, con la restricción `kind == peak` para slots develop;
   4. usar cualquier candidato **no rechazado** de `candidates.json` no usado aún, por `score_cv`, con la restricción `kind == peak` para slots develop;
   5. rellenar con imágenes (`kind == image`), aunque repitan;
   6. si aún faltan slots → fallback parcial de rol `develop` (Capa 5).

### 6.3 Cálculo de `in`/`out` (pico sobre beat)

```python
beats = slot.beats_rel_f                       # offsets en frames, beats[0] == 0
if role == "close" or kind == "calm":
    lead_f = d_f // 2                           # centrado
elif len(beats) >= 2:
    lead_f = beats[config.peak_beat_index]      # por defecto 1: el pico cae en el 2.º beat del slot
else:
    lead_f = round(0.35 * d_f)                  # fallback (slot de 1 beat)

# Rampa de velocidad (solo hook, kind == peak, >= 2 beats; config.hook_ramp):
# 1.0x → ramp_speed (0.4) durante ramp_frames (12) frames de salida centrados
# en el beat del pico → 1.0x. Escalón duro, sin easing.
if ramp:
    a = max(0, lead_f - n // 2); b = min(d_f, a + n); n_eff = b - a
    need_s = (d_f - n_eff) / 30 + n_eff / 30 * s     # segundos de fuente consumidos
    lead_src_s = a / 30 + (lead_f - a) / 30 * s      # fuente desde in_s hasta el pico
    effect = "ramp"; effect_params = {ramp_speed: s, ramp_frames: n_eff, ramp_start_f: a}
else:
    need_s = d_f / 30
    lead_src_s = lead_f / 30
in_s = t_peak - lead_src_s
in_s = clamp(in_s, window[0], window[1] - need_s)   # válido porque admits garantiza window[1]-need_s >= window[0]
out_s = in_s + need_s
n_frames = d_f                                  # frames de SALIDA del segmento, independiente de la rampa
```

- Si el clamp desplaza `in_s` más de 2 frames (`|in_s − (t_peak − lead_src_s)| > 2/30`) se registra `warning: peak_off_beat` en el clip.
- La admisión (§6.1) se evalúa a 1.0x: la rampa consume *menos* fuente, así que es conservadora.
- La duración total es exacta por construcción: `Σ n_frames == duration_f`.
- Imágenes: `in_s = 0`, `out_s = d_f / 30`, `n_frames = d_f`.
- `timeline_start_f = slot.start_f`, `timeline_end_f = slot.end_f`.

### 6.4 Crop 9:16

Sea `W, H` las dims post-rotación de la fuente y `bbox` la mediana de `subject_bbox` en `[in_s, out_s]` (o el bbox medio del candidato si la serie no cubre el tramo).

1. Si `|W/H − 9/16| < 0.01` → `crop = {x:0, y:0, w:1, h:1}`, sin warning.
2. Si no: ventana 9:16 máxima que cabe: `h_n = 1`, `w_n = (9/16) * H / W` si `W/H > 9/16`; si la fuente es más estrecha que 9:16, `w_n = 1`, `h_n = (16/9) * W / H`.
3. Centro en el centro del bbox, clamp a `[0, 1 − w_n]` y `[0, 1 − h_n]`.
4. `subject_cropped` si el bbox no cabe entero en la ventana (con tolerancia 5 % por lado).
5. **Factor de upscale** = `1080 / (w_n * W)`. Si > 1.3 → `warning: upscale_gt_1.3` y `layout = "blur_pad"` si `config.allow_blur_pad` (por defecto true); si no, `layout = "crop"` y solo warning.

`layout ∈ {crop, blur_pad}`. `blur_pad` = fuente entera escalada a 1080 de ancho, centrada verticalmente sobre un fondo de la misma fuente escalado a 1920 de alto y desenfocado. En `blur_pad` `crop` se ignora en el render pero se sigue calculando y guardando.

### 6.5 Conversión a píxeles (en el planner; se guarda en la EDL)

```python
h_px = even(round(crop.h * H))
if layout == "crop" and not is_916(W, H):
    w_px = even(round(h_px * 9 / 16))
    if w_px > W:                          # caso "más estrecho que 9:16" con redondeo par
        w_px = W if W % 2 == 0 else W - 1
        h_px = even(round(w_px * 16 / 9))
else:
    w_px = even(round(crop.w * W))
x_px = even(round(crop.x * W)); x_px = max(0, min(x_px, W - w_px))
y_px = even(round(crop.y * H)); y_px = max(0, min(y_px, H - h_px))
```

`w_px` se deriva de `h_px` para que el aspecto sea exacto salvo ±1 px de paridad. El resultado va en `clip.crop_px` y el render lo usa tal cual: la regla de redondeo deja de ser una dependencia para re-renderizar.

### 6.6 Efectos por clip

- `effect ∈ {none, kenburns, ramp}`; `kenburns` solo en `kind == image` y si `config.ken_burns` (por defecto true). Parámetros (`zoom_per_frame = 0.0015`, `zoom_max = 1.08`) se copian de config a `clip.effect_params`.
- `ramp` solo en el hook (§6.3): `effect_params` lleva `ramp_speed`, `ramp_frames`, `ramp_start_f` (mezclados con los de `blur_pad` si aplica).
- `blur_pad` copia `{blur_radius: 20, blur_power: 2, bg_brightness: -0.1}` a `clip.effect_params`.
- **Texto del hook** (`config.hook_text`, por defecto true): si `config.hook_line_override` no está vacío, `effect_params` añade `text`, `font` (`hook_text_font`), `font_size` (88 px a 1080, reducido de 4 en 4 con Pillow hasta que la línea quepa en 1000 px; mínimo 40), `text_y` (0.28·h, borde superior de la caja, dentro de la zona segura de Reels), `text_frames = min(hook_text_max_frames=60, d_f)`, `fade_frames` (8). `effect` no cambia (puede ser `ramp`); la presencia de `effect_params.text` es el interruptor del render (§10.1). `hook_line_override` viene de `hooks.json.hook_line` (línea anclada a evidencia o abstención, §5.7) o del texto tecleado por el operador, ambos saneados con `clean_hook_line` (≤ 8 palabras para la salida del LLM).
- **Punch-in cada N cortes de develop** (`config.punch_in`, por defecto true; `config.punch_every`, por defecto 2): `effect_params` añade `punch_frames` (5), `punch_zoom` (1.06) — el corte llega ya a `punch_zoom` y el zoom se relaja hasta 1.0 sobre `punch_frames` frames de salida (snap-in, ease-out). Solo `role == "develop"`, solo vídeo (las imágenes ya llevan Ken Burns), y solo en los índices de develop múltiplos de `punch_every` (`punch_every: 1` = todos los cortes).
- **Flash blanco en el beat pico del hook** (`config.hook_flash`, por defecto true): `effect_params` añade `flash_frame` (= `peak_f`, el frame de salida del beat pico que devuelve `compute_in_out`), `flash_frames` (6) — el frame `flash_frame` sale blanco puro y decae linealmente hasta la imagen original en `flash_frames` frames. Solo `role == "hook"`. El operador decide si lo quiere en la pausa `hook_choice` del web UI, viendo ambas variantes (con y sin flash) antes del render final.

### 6.8 Capa de marca (logo + end card)

- Entrada: `sessions/<name>/brand/brand.json` + `brand/logo.png` (los escribe el formulario web; una marca por sesión, sin default a nivel de repo porque hay varios negocios). `brand.json`: `logo` (relativo a la sesión, por defecto `brand/logo.png`), y opcionales `handle`, `line`, `bg` (`#111111`), `fg` (`#FFFFFF`), `font` (`hook_text_font`). `session.planner.load_brand` añade `logo_sha256`, `logo_w`, `logo_h`; si falta el JSON o el PNG, la capa está apagada sin error.
- `build_edl` guarda `edl.brand` con esos campos y `watermark = {w: logo_w=160, opacity: 0.6, inset_x: 48, bottom_frac: 0.177}` (o `null` si `config.brand` está apagado). El render lo lee de la EDL (§10.6); ningún clip lo lleva en `effect_params`.
- **End card** (`config.end_card`, `end_card_frames = 45`): `build_clips._split_end_card` quita al close sus últimos `k = min(end_card_frames, n_frames_close − 30)` frames (el close es 1.0x: `out_s = in_s + n_frames/30`) y añade un clip sintético `role = end_card`, `effect = end_card`, `type = image`, `src = brand.logo`, con `src_w/src_h = 1080×1920` (su "fuente" es el lienzo) y `effect_params = {bg, fg, font, handle, line, logo_w: 480, logo_h (por aspecto del PNG), text_size: 48}`. `duration_f` y el corte de música no cambian. Si `k < 15` no hay card y se avisa `end_card_skipped`.
- Invariantes: el slot sintético `{slot: close+1, role: end_card, start_f, end_f}` se añade solo a la lista en memoria que recibe `assert_invariants` (`slots.json` no cambia); P9 exime a `end_card` (mínimo 15 frames); P3/P4/P5/P7 ya se saltan por `type == image`. `apply_color_match` ignora el end card.

### 6.7 Igualación de color por clip (`color_fix`)

Los segmentos se renderizan por separado y se concatenan con `-c:v copy`, así que nada iguala exposición ni balance entre fuentes grabadas en luces distintas. El planner mide cada clip una vez y guarda una corrección pequeña en la EDL; el render sólo emite un filtro más (§10). Sin etapa nueva ni dependencias.

- **Medida** (`planner/color.py:measure_clip_color`): `ffprobe -f lavfi -i "movie=<proxy>:seek_point=<in_s>,trim=duration=<out_s - in_s>,signalstats"`, media de `YAVG/UAVG/VAVG/SATAVG` (0-255) sobre los frames del clip. Imágenes: la misma llamada sobre el `normalized` jpg (1 frame). Se mide sobre el **proxy** (ya bt709 SDR, §3.2) → el mismo `color_fix` sirve para preview y final, y R2 se mantiene.
- **Objetivo** = mediana por clave (`statistics.median`) entre todos los clips del reel, no "gris neutro": un reel cálido sigue cálido, sólo se mueven los outliers.
- **Corrección** (`color_fix_for`, con `s = config.color_match_strength`, por defecto 0.7) — **sólo luma**:
  - `brightness = clamp(s·(Y_t − Y_m)/255, 0, 0.15)` — **sólo levanta**: un clip a Y≈110+ (~45 IRE) ya está bien expuesto según referencias de coloristas (piel en 40-70 IRE), y oscurecerlo hacia una mediana arrastrada por clips oscuros se veía mal.
  - Ganancia verificada empíricamente en ffmpeg 5.1 (2026-09-15): `eq=brightness=0.1` sube Y ≈ 25. Signo positivo = subir el plano, de ahí el `/255` (no `/128`).
  - **Sin saturación ni balance de croma** (`colorcorrect`/`saturation`, retirados 2026-09-18): `UAVG`/`VAVG`/`SATAVG` promedian el frame completo, así que miden lo que hay en plano (piel, madera, cielo) y no el balance de blancos; aplicar un offset de croma sobre eso arrastraba los neutros hacia naranja en vez de corregirlo, y `SATAVG` es de un solo dígito en clips típicos — demasiado ruidoso para fijar una ganancia de saturación sin quemar la piel. No reintroducir sin una medida real de balance de blancos (p. ej. sobre píxeles casi neutros).
- Se guarda `clip.color_fix = {brightness, measured}`; `measured` sigue midiendo `y/u/v/sat` (sirve para depurar) aunque sólo `y` se use. `config.color_match = false` deja la clave ausente y el render se comporta como antes.
- Los clamps y `strength` son los mandos de calibración: evitan aplanar un plano deliberadamente oscuro. Corrección estática por clip (sin adaptación temporal ni matching de histograma); ampliar si en metraje real no basta.
