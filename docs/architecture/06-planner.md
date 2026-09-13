[← README](README.md)

## 6. Capa 4 — Planner determinista (snapper)

Todo en frames de 30 fps. Notación: `d_f` = duración del slot en frames; `speed` = 1.0 salvo override de config para hook (0.5 permitido, resto de valores no).

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
need_s = d_f / 30 * speed
beats = slot.beats_rel_f                       # offsets en frames, beats[0] == 0
if role == "close" or kind == "calm":
    lead_f = d_f // 2                           # centrado
elif len(beats) >= 2:
    lead_f = beats[config.peak_beat_index]      # por defecto 1: el pico cae en el 2.º beat del slot
else:
    lead_f = round(0.35 * d_f)                  # fallback (slot de 1 beat)
lead = lead_f / d_f
in_s = t_peak - lead * need_s
in_s = clamp(in_s, window[0], window[1] - need_s)   # válido porque admits garantiza window[1]-need_s >= window[0]
out_s = in_s + need_s
n_frames = d_f                                  # frames de SALIDA del segmento, independiente de speed
```

- Si el clamp desplaza `in_s` más de 2 frames (`|in_s − (t_peak − lead·need_s)| > 2/30`) se registra `warning: peak_off_beat` en el clip.
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

- `effect ∈ {none, kenburns}`; `kenburns` solo en `kind == image` y si `config.ken_burns` (por defecto true). Parámetros (`zoom_per_frame = 0.0015`, `zoom_max = 1.08`) se copian de config a `clip.effect_params`.
- `blur_pad` copia `{blur_radius: 20, blur_power: 2, bg_brightness: -0.1}` a `clip.effect_params`.


