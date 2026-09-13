[← README](README.md)

## 4. Capa 2 — Features locales

### 4.1 Audio → slots (`slots.json`)

1. **Beats:** `librosa.beat.beat_track(y, sr, units="time")` sobre `track_cut.wav` → `tempo`, `beats_s`.
2. **Confianza:** `[validar umbral]` autocorrelación de `onset_strength` en el lag del tempo; si el pico normalizado < 0.3 o `tempo` < 50 o > 200 → `beats_confident = false` y se usa **grid uniforme** de 1.6 s (`48 frames`), con "beats" sintéticos cada 24 frames para que la alineación a beat del planner siga funcionando.
3. **Cuantización a frames:** `beats_f = sorted(set(round(b * 30)))`, se fuerza `0` al inicio y `duration_f` al final.
4. **Agrupación:** `beats_per_slot = ceil(tempo / 60)` (mínimo entero tal que `beats_per_slot · 60 / tempo ≥ 1.0 s`). Ej.: 128 bpm → 3 beats/slot (1.41 s). Se agrupan los beats de `beats_per_slot` en `beats_per_slot` empezando por el primer beat ≥ 0. No hay detección de compás en v4.
5. **Residuo:** si el último slot resultante tiene < 30 frames, se fusiona con el **anterior**. Cualquier slot interior < 30 frames se fusiona con el anterior.
6. **Roles:** `hook` = slot que empieza en 0; `close` = slot que termina en `duration_f`; `develop` = resto. Si solo hay 2 slots, no hay `develop`. Si solo hay 1, error.
7. **Beats por slot:** cada slot guarda `beats_rel_f`, los offsets en frames de los beats que contiene, relativos a `start_f`, incluyendo `0`. Los usa el planner (§6.3).

```json
{
  "music_cut": "music/track_cut.wav",
  "music_cut_sha256": "…",
  "duration_f": 480,
  "tempo_bpm": 128.0,
  "beats_confident": true,
  "beats_per_slot": 3,
  "slots": [
    { "slot": 0, "start_f": 0,   "end_f": 42,  "role": "hook",    "beats_rel_f": [0, 14, 28] },
    { "slot": 1, "start_f": 42,  "end_f": 84,  "role": "develop", "beats_rel_f": [0, 14, 28] },
    { "slot": 11, "start_f": 448, "end_f": 480, "role": "close",  "beats_rel_f": [0, 14] }
  ]
}
```

Invariantes: `start_f[i+1] == end_f[i]`, `start_f[0] == 0`, `end_f[-1] == duration_f`, todo slot ≥ 30 frames, `beats_rel_f[0] == 0`.

### 4.2 Vídeo → series por frame

Sobre cada proxy, muestreo a 10 fps (cada 3.º frame; el índice de frame del proxy es `i * 3`, tiempo `= i * 3 / 30`):

- **Tracking multi-persona:** YOLO-pose (ultralytics `yolov8n-pose` o superior; sha256 del `.pt` en `features_config`) → bboxes + 17 keypoints por persona → tracker por IoU (asignación greedy, IoU ≥ 0.3, tolerancia 5 muestras sin match) → `tracks[]`.
- **Sujeto principal** = track con mayor `Σ (kp_speed · área_bbox)` en la ventana. Se recalcula por ventana de candidato, no por clip.
- `subject_bbox[i]`: bbox del sujeto principal, EMA α = 0.3, normalizado 0–1 post-rotación.
- `subject_visible[i]`: hay bbox del sujeto principal.
- `kp_speed[i]`: velocidad media de muñecas, codos, caderas y rodillas del sujeto principal entre muestras consecutivas, **normalizada por la altura del bbox** (invariante a distancia de cámara), suavizada EMA α = 0.5, normalizada por clip (p5–p95). Es la señal de acción del atleta.
- `motion_bg[i]`: media de |frame_i − frame_{i−1}| tras blur 5×5 **fuera** de todos los bboxes de personas, normalizada por clip. Es el estimador de movimiento de cámara.
- `motion[i]` (global, como v3): se conserva solo para diagnóstico e histogramas.
- `sharpness[i]`: varianza del Laplaciano en gris **dentro del bbox del sujeto**, normalizada por clip (p5–p95). Nota: es relativa al clip; no se compara entre clips (ver §8.3).
- `multi_subject[i]`: ≥ 2 tracks con área > 20 % del frame.
- `scene_cuts`: PySceneDetect `ContentDetector`, umbral por defecto `[validar]` — en gimnasio los whip pans generan falsos cortes que amputan ventanas; guardar en el log el nº de cortes por clip y revisar si > 3 en un clip de 25 s.

Se persisten en `features/<src>.parquet` junto con `features_config_sha256`.

### 4.3 Candidatos (`candidates.json`)

Dos tipos:

**`peak`** — picos locales de `kp_speed`:
1. Picos con `scipy.signal.find_peaks(kp_speed, distance=10)` (≥ 1 s entre picos a 10 fps; permite que el tirón y la caída de la barra sean candidatos distintos), prominencia ≥ 0.2 `[validar]`.
2. Descarte: `sharpness < 0.35` `[validar]`, `subject_visible == false`, `motion_bg > 0.6` en el pico `[validar]` (cámara moviéndose), o a menos de `edge_margin` de un corte de escena o del borde del clip, donde `edge_margin = 0.5 s` si el clip dura ≥ 5 s, `0.25 s` si es más corto.
3. Ventana: `[t_min, t_max]` = mayor tramo alrededor del pico sin corte de escena, con sujeto visible y `sharpness ≥ 0.35`, limitado a ±6 s.

**`calm`** — tramos estables (para `close`, opcionalmente hook "de preparación"):
1. Tramos contiguos ≥ 2 s con `kp_speed ≤ 0.25` **y** `motion_bg ≤ 0.25` `[validar]`, `sharpness ≥ 0.5`, sujeto visible y centrado (`|cx − 0.5| ≤ 0.2`, `|cy − 0.5| ≤ 0.25`).
2. `t_peak` = centro del tramo, ventana = el tramo.
3. Máximo 2 por clip (los dos más largos).

**Imágenes**: un candidato `kind: "image"`, `t_peak = 0`, `window = [0, 1e9]`.

**Frames de pico:** por cada candidato de vídeo se extraen 3 JPEG del proxy (`t_peak − 0.3`, `t_peak`, `t_peak + 0.3`, clamp a la ventana), 512 px lado largo, quality 85, más una hoja de contacto horizontal de los 3 (solo para inspección humana, no se envía):

```bash
ffmpeg -y -ss {t} -i proxies/take_01.mp4 -frames:v 1 -vf "scale='if(gt(iw,ih),512,-2)':'if(gt(iw,ih),-2,512)'" -q:v 4 peaks/c01_1.jpg
```

Para imágenes se envía un solo JPEG.

**Admisibilidad precalculada:** `admits_slots[]` = slots cuya duración cabe en la ventana según §6.1 (con `speed` de config). Un candidato con `admits_slots == []` se guarda pero **no se envía al LLM**.

```json
{
  "session_id": "…",
  "manifest_sha256": "…",
  "features_config_sha256": "…",
  "pose_model_sha256": "…",
  "candidates": [
    {
      "id": "c01",
      "src": "inputs/take_01.mov",
      "kind": "peak",
      "t_peak": 6.40,
      "window": [4.80, 9.20],
      "kp_speed": 0.91,
      "motion_bg": 0.18,
      "sharpness": 0.78,
      "subject_bbox": [0.31, 0.12, 0.72, 0.95],
      "multi_subject": false,
      "score_cv": 0.81,
      "admits_slots": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
      "peak_frames": ["peaks/c01_0.jpg", "peaks/c01_1.jpg", "peaks/c01_2.jpg"],
      "peak_frames_sha256": ["…", "…", "…"]
    },
    {
      "id": "c07",
      "src": "inputs/take_03.mov",
      "kind": "calm",
      "t_peak": 14.10,
      "window": [12.90, 15.60],
      "kp_speed": 0.12,
      "motion_bg": 0.09,
      "sharpness": 0.83,
      "subject_bbox": [0.36, 0.15, 0.66, 0.92],
      "multi_subject": false,
      "score_cv": 0.62,
      "admits_slots": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
      "peak_frames": ["peaks/c07_0.jpg", "peaks/c07_1.jpg", "peaks/c07_2.jpg"],
      "peak_frames_sha256": ["…", "…", "…"]
    },
    {
      "id": "c14",
      "src": "inputs/img_05.jpg",
      "kind": "image",
      "t_peak": 0.0,
      "window": [0.0, 1000000000.0],
      "kp_speed": 0.0,
      "motion_bg": 0.0,
      "sharpness": 0.85,
      "subject_bbox": [0.25, 0.10, 0.75, 0.90],
      "multi_subject": false,
      "score_cv": 0.43,
      "admits_slots": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
      "peak_frames": ["peaks/c14_1.jpg"],
      "peak_frames_sha256": ["…"]
    }
  ]
}
```

Meta: 20–40 candidatos para 10–12 clips, con ≥ 2 `calm`. Si hay < `N_SLOTS` candidatos admisibles se continúa (el planner relaja), pero se emite `warning: few_candidates` en el log y la EDL.

`score_cv = 0.5·kp_speed + 0.3·sharpness + 0.2·centralidad` (`centralidad = 1 − 2·|cx − 0.5|`); lo usa el fallback y la relajación del planner. Para `calm` se usa `0.5·(1 − kp_speed)` en el primer término.

### 4.4 Verificación proxy ↔ original (obligatoria, una vez por fuente)

Se ejecuta aquí, cuando ya existe la serie `kp_speed` del proxy. Para los 5 instantes `t` de mayor `kp_speed` separados ≥ 2 s (si hay menos de 5, se completan con `{10 %, 50 %, 90 %}` de la duración):

```bash
ffmpeg -ss {t} -i inputs/take_01.mov -frames:v 1 -vf "{tonemap_chain},scale=256:-2" /tmp/orig_{t}.png
for k in -2 -1 0 1 2:
  ffmpeg -ss {t + k/30} -i proxies/take_01.mp4 -frames:v 1 -vf "scale=256:-2" /tmp/proxy_{t}_{k}.png
```

`d_k = hamming(phash(orig), phash(proxy_k))`. Condiciones por instante: `argmin_k d_k == 0`, `d_0 ≤ 6`, y `d_0 < min(d_-1, d_1)` `[validar margen]`. Si los 5 instantes pasan → `proxy_verified: true`. Si falla en alguno, la sesión se detiene con error: el mapeo temporal no es fiable y nada aguas abajo tiene sentido. Comparar en máximos de movimiento es lo que hace detectable un desfase de un frame; en tramos estáticos el pHash no distingue ni 0.5 s.


