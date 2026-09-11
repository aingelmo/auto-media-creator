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

## 1. Convenciones globales

| Convención | Valor |
|---|---|
| Target | 1080×1920, 30 fps CFR, H.264 High, yuv420p, BT.709 tv-range, AAC 192k 48 kHz |
| Unidad de tiempo en planner y EDL | **frames a 30 fps** (`int`). Los segundos solo aparecen como derivados (`n/30`). |
| Tiempo de fuente (`in_s`) | **relativo al inicio del fichero**, tal como lo espera `-ss` de entrada por defecto (sin `-seek_timestamp`, `-ss` se desplaza por el `start_time` del fichero `[verificado: doc ffmpeg -seek_timestamp]`). Nunca se suma `start_time_s`. Nunca se usa `-seek_timestamp`. |
| Espacio de coordenadas | post-rotación (autorotate activo en todos los pasos; nunca `-c:v copy` en pasos intermedios de vídeo). |
| Crop | normalizado 0–1 en el espacio post-rotación; se convierte a píxeles en el planner y **se guarda también en píxeles** en la EDL. |
| Pista musical | se recorta **una sola vez** a `music/track_cut.wav` (48 kHz, estéreo). Beats, loudnorm y render usan ese WAV; nunca se hace `-ss` sobre el MP3 más de una vez. |
| Modelo | `GEMINI_MODEL` (env), por defecto `gemini-3.7-flash` (mismo precio que 3.8; ver §11). |
| Hilos de codificación | `-threads {render_profile.threads}` fijo (por defecto 4). x264 solo es determinista para el mismo número de hilos. |
| Forma canónica de `speed` | `setpts=PTS/{speed},fps=30` (siempre `setpts` **antes** de `fps`). Con fuente 30 fps y `speed=0.5` duplica frames (15 fps efectivos); con fuente 60 fps da slow-motion real. |

Directorio de una sesión:

```
sessions/<session_id>/
  inputs/            clips y fotos originales (solo lectura)
  music/track.mp3    original (solo lectura)
  music/track_cut.wav
  manifest.json
  proxies/
  peaks/             3 JPEG por candidato (+ contact sheet por candidato para inspección)
  features/          series por clip (parquet/npz)
  candidates.json
  slots.json
  selection.json     (+ selection_attempt_N.json)
  edl.json
  segments/          seg_NN.mp4 (render final)
  preview_segments/  seg_NN.mp4 (render desde proxies, siempre)
  preview.mp4
  reel.mp4
  render_profile.json
  log.jsonl
```

---

## 2. Diagrama de capas

```text
[10-12 clips iPhone (HEVC 10-bit HLG / DV 8.4, VFR, 4K, rotación en metadatos)] + [fotos HEIC/JPEG] + [pista musical]
       │
       ▼
┌──────────────────────────────────────────────────────────────┐
│ Capa 1: Ingesta (ffprobe + FFmpeg + Pillow)                  │
│  - manifest.json (dims pre/post-rotación, rotación, color,   │
│    hdr, start_time, duración, sha256)                        │
│  - Proxies 720p CFR 30 SDR sin audio, timeline desde 0       │
│  - Fotos normalizadas (EXIF, HEIC→JPEG sRGB)                 │
│  - Pista recortada a track_cut.wav                           │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────┐
│ Capa 2: Features locales (0 € API)                           │
│  Audio (WAV): beats → grid en frames → slots (+beats/slot)   │
│  Vídeo (proxies): escenas, nitidez, kp_speed, motion_bg,     │
│   tracking multi-persona → candidatos `peak`/`calm` + JPEG   │
│  Verificación proxy↔original por pHash en máximos de kp_speed│
└──────────────────────────────┬───────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────┐
│ Capa 3: Selector (Gemini, Interactions API, structured out.) │
│  Entrada: solo candidatos admisibles, imágenes `low` inline  │
│  Salida: selection.json                                      │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────┐
│ Capa 4: Planner determinista (snapper, en frames, a beat)    │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────┐
│ Capa 5: Validador (S-checks, asserts de planner, warnings)   │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────┐
│ Capa 6: Preview por segmento desde proxies (siempre)         │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────┐
│ Capa 7: Render (segmentos crf 18 → R-checks → concat copy    │
│         → audio 2 pasadas → R-checks finales)                │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
                    [reel.mp4 1080x1920]
```

---

## 3. Capa 1 — Ingesta

### 3.1 manifest.json

```json
{
  "session_id": "2026-09-11_gymA",
  "target": { "w": 1080, "h": 1920, "fps": 30 },
  "music": {
    "src": "music/track.mp3", "src_sha256": "…",
    "offset_s": 12.0, "max_duration_s": 20.0,
    "cut": "music/track_cut.wav", "cut_sha256": "…"
  },
  "sources": [
    {
      "src": "inputs/take_01.mov",
      "sha256": "…",
      "type": "video",
      "raw_w": 3840, "raw_h": 2160,
      "rotation": 90,
      "w": 2160, "h": 3840,
      "duration_s": 24.533,
      "start_time_s": 0.0,
      "nb_frames_est": 736,
      "vfr": true,
      "src_fps_nominal": 30.0,
      "hdr": "hlg",
      "color": { "primaries": "bt2020", "trc": "arib-std-b67", "space": "bt2020nc", "range": "tv" },
      "proxy": "proxies/take_01.mp4",
      "proxy_verified": false
    },
    {
      "src": "inputs/img_05.jpg",
      "sha256": "…",
      "type": "image",
      "w": 3024, "h": 4032,
      "normalized": "inputs_norm/img_05.jpg"
    }
  ]
}
```

Reglas de cálculo:

- `raw_w/raw_h` = `streams[v].width/height` de ffprobe. `rotation` = `side_data_list[].rotation` del displaymatrix (0 si ausente). `w/h` (post-rotación) = swap de raw si `|rotation| ∈ {90, 270}`. ffprobe no da las dims post-rotación; las calcula el código.
- `hdr` ∈ `none | hlg | pq | dv84`. Detección: `color_transfer` = `arib-std-b67` → `hlg`; `smpte2084` → `pq`; presencia de `side_data` Dolby Vision con base HLG → `dv84` (se trata como `hlg`: el RPU se ignora y se usa la capa base; el perfil 8.4 es por definición compatible con HLG en la capa base `[verificado]`, la validación pendiente es solo visual). Si `color_transfer` es `unknown` o falta en un fichero de 10 bits → **error de ingesta**, no se asume SDR (evita el "vídeo lavado etiquetado bt709").
- `vfr` = `r_frame_rate ≠ avg_frame_rate` o desviación de `pkt_duration_time` > 5 %. `src_fps_nominal` = `avg_frame_rate` redondeado; se usa solo para el warning `slowmo_duplicates` (hook con `speed=0.5` sobre fuente ≤ 30 fps).
- `start_time_s` y `color` se registran para diagnóstico y para la EDL. **No entran en ningún cálculo de tiempo.**
- `proxy_verified` pasa a `true` en Capa 2 (§4.4), no aquí.

### 3.2 Proxies

Objetivo: 720 en el lado corto, CFR 30, SDR BT.709, sin audio, primer frame en pts 0.

```bash
# HDR (hlg / dv84). Para pq: tin=smpte2084 y npl según [validar].
ffmpeg -y -i inputs/take_01.mov \
  -vf "fps=30,setpts=PTS-STARTPTS,\
zscale=tin=arib-std-b67:t=linear:npl=1000,format=gbrpf32le,zscale=p=bt709,tonemap=hable:desat=0,\
zscale=t=bt709:m=bt709:r=tv,format=yuv420p,\
scale='if(gt(iw,ih),-2,720)':'if(gt(iw,ih),720,-2)'" \
  -fps_mode cfr -avoid_negative_ts make_zero \
  -color_primaries bt709 -color_trc bt709 -colorspace bt709 -color_range tv \
  -c:v libx264 -crf 24 -preset veryfast -g 30 -threads {threads} -an \
  proxies/take_01.mp4

# SDR: mismo comando sin la cadena zscale/tonemap.
```

Notas:

- `fps=30` va **antes** del tonemap para no tonemapear frames que se descartan.
- `tin=arib-std-b67` explícito: si el fichero no viene etiquetado, zscale falla ruidosamente en vez de producir un resultado incorrecto en silencio.
- `npl=1000` con HLG `[validar]` (semántica de `peak_luminance` en zimg para HLG no verificada). El valor y el filtro exacto se fijan en la Sesión 0 comparando con la alternativa `libplacebo`:
  `libplacebo=colorspace=bt709:color_primaries=bt709:color_trc=bt709:tonemapping=bt.2390:format=yuv420p` (requiere build con Vulkan; en Docker sin GPU exige lavapipe, rendimiento `[validar]`). Aviso: en libplacebo `apply_dolbyvision` está activo por defecto y con RPU presente la salida interna pasa a BT.2020+PQ `[verificado: doc vf_libplacebo]`; para que DV 8.4 se trate igual que HLG hay que pasar `apply_dolbyvision=false`.
- La cadena de tonemap elegida se guarda en `render_profile.tonemap_chain` y se usa idéntica en proxy, preview y render.
- `-g 30`: keyframe cada segundo para que `-ss` sobre el proxy (extracción de JPEG de pico, preview) sea rápido y exacto.

### 3.3 Imágenes

Normalización con Pillow antes de cualquier FFmpeg:

```python
from PIL import Image, ImageOps
import pillow_heif; pillow_heif.register_heif_opener()

im = Image.open(path)
im = ImageOps.exif_transpose(im)          # aplica orientación EXIF
im = im.convert("RGB")                     # descarta gain map / alpha
im.save(out, "JPEG", quality=92, icc_profile=None)  # sRGB
```

`w/h` del manifest son los de la imagen normalizada. Sin duración propia.

### 3.4 Pista musical

```bash
ffmpeg -y -ss {offset_s} -t {max_duration_s} -i music/track.mp3 \
  -ar 48000 -ac 2 -c:a pcm_s16le music/track_cut.wav
```

El seek sobre MP3 no es sample-exacto (frames de 1152 muestras, encoder delay, estimación de bitrate sin TOC). Al hacerlo **una sola vez** y consumir el WAV en todo lo demás, el error queda "horneado" y es el mismo para beats, loudnorm y render. `t = 0` del WAV es el inicio del Reel.

---

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

---

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

```text
Eres un editor de vídeo profesional especializado en Reels verticales (9:16) de gimnasio.

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
- reason: máximo 12 palabras. Responde únicamente con el JSON del schema.
```

### 5.5 User prompt (dinámico)

```text
OBJETIVO: Reel de {duration_s} s. Temática: resumen dinámico de entrenamiento.

SLOTS (N_SLOTS = {n}): 1 hook, {n-2} develop, 1 close.

LISTA CANÓNICA DE EJERCICIOS:
back squat, front squat, overhead squat, deadlift, clean, snatch, jerk, thruster, pull-up, muscle-up, push-up, burpee, box jump, wall ball, kettlebell swing, rowing, bike, ski erg, run, rope climb, handstand, double-under, other

CANDIDATOS: {n_cand} (ids: {ids}). Los fotogramas de cada uno preceden a este mensaje, etiquetados con su id.

Genera la selección.
```

Se adjunta a cada candidato solo `id`, `kind`, `src`, `multi_subject`; no se pasan `kp_speed`/`sharpness` (sesgan al modelo hacia lo que ya sabe el código) ni duraciones de slot (el modelo no decide tiempos). Los candidatos no admisibles no se envían.

### 5.6 Validación sintáctica y reintentos

- El schema forzado hace que el JSON sea válido salvo truncado (`status == "incomplete"`). Si ocurre → reintento con `thinking_level: low` y prompt reforzado "reason ≤ 8 palabras".
- Máximo 2 reintentos al LLM en total por sesión, y solo por `status: incomplete`. El resto se repara en código o con fallback **parcial**.
- Cada intento se guarda como `selection_attempt_N.json` con `usage` (tokens de entrada, salida y thinking), `status` y coste calculado.

---

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

---

## 7. Contrato EDL v4 (`edl.json`, lo genera código)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "version": { "type": "integer", "const": 4 },
    "session_id": { "type": "string" },
    "inputs": {
      "type": "object",
      "properties": {
        "manifest_path": { "type": "string" },
        "manifest_sha256": { "type": "string" },
        "candidates_sha256": { "type": "string" },
        "selection_sha256": { "type": ["string", "null"] },
        "slots_sha256": { "type": "string" },
        "features_config_sha256": { "type": "string" },
        "pose_model_sha256": { "type": "string" }
      },
      "required": ["manifest_path", "manifest_sha256", "candidates_sha256", "selection_sha256", "slots_sha256", "features_config_sha256", "pose_model_sha256"]
    },
    "render_profile": {
      "type": "object",
      "description": "Todo lo que necesita el render para ser bit a bit reproducible.",
      "properties": {
        "ffmpeg_version": { "type": "string" },
        "ffmpeg_configuration": { "type": "string" },
        "libx264_version": { "type": "string" },
        "zimg_version": { "type": ["string", "null"] },
        "threads": { "type": "integer", "minimum": 1 },
        "tonemap_chain": { "type": "string" },
        "tonemap_chain_pq": { "type": ["string", "null"] },
        "video_codec_args": { "type": "string", "description": "String exacto de flags de codec de §10.1" },
        "segment_filter_template": { "type": "string" },
        "blur_pad_filter_template": { "type": "string" },
        "image_filter_template": { "type": "string" },
        "audio_codec_args": { "type": "string" },
        "profile_sha256": { "type": "string" }
      },
      "required": ["ffmpeg_version", "ffmpeg_configuration", "libx264_version", "zimg_version", "threads", "tonemap_chain", "tonemap_chain_pq", "video_codec_args", "segment_filter_template", "blur_pad_filter_template", "image_filter_template", "audio_codec_args", "profile_sha256"]
    },
    "target": {
      "type": "object",
      "properties": {
        "w": { "type": "integer", "const": 1080 },
        "h": { "type": "integer", "const": 1920 },
        "fps": { "type": "integer", "const": 30 },
        "duration_f": { "type": "integer", "minimum": 30 }
      },
      "required": ["w", "h", "fps", "duration_f"]
    },
    "clips": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "properties": {
          "slot": { "type": "integer", "minimum": 0 },
          "role": { "type": "string", "enum": ["hook", "develop", "close"] },
          "candidate_id": { "type": "string" },
          "src": { "type": "string" },
          "src_sha256": { "type": "string" },
          "type": { "type": "string", "enum": ["video", "image"] },
          "src_w": { "type": "integer" },
          "src_h": { "type": "integer" },
          "src_rotation": { "type": "integer" },
          "src_color": {
            "type": "object",
            "properties": {
              "primaries": { "type": "string" }, "trc": { "type": "string" },
              "space": { "type": "string" }, "range": { "type": "string" }
            },
            "required": ["primaries", "trc", "space", "range"]
          },
          "hdr": { "type": "string", "enum": ["none", "hlg", "pq", "dv84"] },
          "in_s": { "type": "number", "minimum": 0, "description": "Relativo al inicio del fichero. Se pasa tal cual a -ss." },
          "out_s": { "type": "number" },
          "n_frames": { "type": "integer", "minimum": 30 },
          "speed": { "type": "number", "enum": [0.5, 1.0] },
          "timeline_start_f": { "type": "integer", "minimum": 0 },
          "timeline_end_f": { "type": "integer" },
          "layout": { "type": "string", "enum": ["crop", "blur_pad"] },
          "crop": {
            "type": "object",
            "description": "Normalizado 0-1, espacio post-rotación",
            "properties": {
              "x": { "type": "number", "minimum": 0, "maximum": 1 },
              "y": { "type": "number", "minimum": 0, "maximum": 1 },
              "w": { "type": "number", "exclusiveMinimum": 0, "maximum": 1 },
              "h": { "type": "number", "exclusiveMinimum": 0, "maximum": 1 }
            },
            "required": ["x", "y", "w", "h"]
          },
          "crop_px": {
            "type": "object",
            "description": "Píxeles, espacio post-rotación; es lo que consume el render",
            "properties": {
              "x": { "type": "integer", "minimum": 0 }, "y": { "type": "integer", "minimum": 0 },
              "w": { "type": "integer", "minimum": 2 }, "h": { "type": "integer", "minimum": 2 }
            },
            "required": ["x", "y", "w", "h"]
          },
          "effect": { "type": "string", "enum": ["none", "kenburns"] },
          "effect_params": { "type": "object" },
          "warnings": { "type": "array", "items": { "type": "string" } }
        },
        "required": ["slot", "role", "candidate_id", "src", "src_sha256", "type", "src_w", "src_h", "src_rotation", "src_color", "hdr", "in_s", "out_s", "n_frames", "speed", "timeline_start_f", "timeline_end_f", "layout", "crop", "crop_px", "effect", "effect_params", "warnings"]
      }
    },
    "audio": {
      "type": "object",
      "properties": {
        "music_cut_path": { "type": ["string", "null"] },
        "music_cut_sha256": { "type": ["string", "null"] },
        "music_src_path": { "type": ["string", "null"] },
        "music_src_sha256": { "type": ["string", "null"] },
        "music_offset_s": { "type": "number", "minimum": 0 },
        "target_lufs": { "type": "number" },
        "target_tp": { "type": "number" },
        "target_lra": { "type": "number" },
        "loudnorm_measured": { "type": ["object", "null"], "description": "Salida JSON de la 1.ª pasada; null hasta el render." },
        "loudnorm_applied": { "type": ["object", "null"], "description": "Salida JSON de la 2.ª pasada (incluye normalization_type); null hasta el render." },
        "fade_out_s": { "type": "number", "minimum": 0 }
      },
      "required": ["music_cut_path", "music_cut_sha256", "music_src_path", "music_src_sha256", "music_offset_s", "target_lufs", "target_tp", "target_lra", "loudnorm_measured", "loudnorm_applied", "fade_out_s"]
    },
    "provenance": {
      "type": "object",
      "properties": {
        "planner": { "type": "string", "enum": ["llm", "rules_fallback", "mixed"] },
        "fallback_roles": { "type": "array", "items": { "type": "string", "enum": ["hook", "develop", "close"] } },
        "model": { "type": ["string", "null"] },
        "sdk_version": { "type": ["string", "null"] },
        "api_revision": { "type": ["string", "null"] },
        "llm_attempts": { "type": "integer" },
        "llm_usage": { "type": ["object", "null"] },
        "llm_cost_usd": { "type": "number" },
        "warnings": { "type": "array", "items": { "type": "string" } }
      },
      "required": ["planner", "fallback_roles", "model", "sdk_version", "api_revision", "llm_attempts", "llm_usage", "llm_cost_usd", "warnings"]
    }
  },
  "required": ["version", "session_id", "inputs", "render_profile", "target", "clips", "audio", "provenance"]
}
```

Cambios frente a v3: `render_profile` (versiones, configuración de FFmpeg, hilos, cadenas y flags exactos, hash); `crop_px`, `src_rotation`, `src_color`, `effect`/`effect_params` por clip; `music_cut_*` y `music_src_*` con hashes; `target_tp/target_lra`; `loudnorm_applied`; `sdk_version`, `api_revision`, `llm_usage`; hashes de config de features y del modelo de pose. `audio.music_cut_path = null` es válido y produce un render con `-an` (derechos de música). Este schema se valida localmente con `jsonschema` (draft-07 sí soporta `const` y `exclusiveMinimum`); **no se envía a Gemini**.

---

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
| P5 | `round((out_s − in_s) / speed * 30) == n_frames` |
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
| W4 | Hook con `speed == 0.5` y `src_fps_nominal ≤ 30` | `slowmo_duplicates` |
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

---

## 9. Capa 6 — Preview

Mismo código de render (Capa 7) sobre los proxies, **por segmento**, salida 540×960, `-preset ultrafast -crf 30`, sin loudnorm (solo `volume`). Se genera **siempre**: los segmentos de preview son la referencia de los checks R2 (§10.5). El `preview.mp4` concatenado es obligatorio revisar cuando hay W1–W5 o `planner != llm`; recomendado siempre en las primeras 10 sesiones. Los `in_s/out_s` son válidos tal cual sobre el proxy (misma convención de tiempo, verificada en §4.4). El crop en píxeles del preview se recalcula desde `crop` normalizado con las dims del proxy (misma regla de §6.5).

---

## 10. Capa 7 — Render

Todos los comandos llevan `-threads {threads}` y los flags exactos se serializan en `render_profile`.

### 10.1 Segmento de vídeo (`layout == crop`)

```bash
# {src_hdr}: render_profile.tonemap_chain seguida de coma, o vacío si hdr == none
# {t_safety} = n_frames/30*speed + 0.5   (solo tope de lectura; el corte exacto lo da -frames:v)
ffmpeg -y -ss {in_s} -t {t_safety} -i {src} \
  -vf "crop={crop_px.w}:{crop_px.h}:{crop_px.x}:{crop_px.y},\
setpts=PTS/{speed},fps=30,\
scale=1080:1920:flags=lanczos,\
{src_hdr}setsar=1,format=yuv420p" \
  -fps_mode cfr -frames:v {n_frames} \
  -color_primaries bt709 -color_trc bt709 -colorspace bt709 -color_range tv \
  -an -c:v libx264 -crf 18 -preset medium -profile:v high -pix_fmt yuv420p \
  -video_track_timescale 30000 -g 60 -keyint_min 60 -sc_threshold 0 -threads {threads} \
  segments/seg_{slot:02d}.mp4
```

- Orden del filtro: `crop` (reduce píxeles) → `setpts` (velocidad) → `fps` (fija cadencia **después** de la velocidad) → `scale` → tonemap → `setsar`.
  - Con `speed == 1.0`, `setpts=PTS/1.0` es un no-op.
  - Con `speed == 0.5`: `setpts=PTS/0.5` estira los timestamps; `fps=30` duplica frames (fuente 30 fps) o los conserva (fuente 60 fps). Se consumen `d_f/60` s de fuente y se emiten `d_f` frames, coherente con §6.3. **El orden inverso (`fps` antes de `setpts`) produce un segmento con la mitad de frames a cadencia 15 fps y hace fallar R1**; no usar.
  - `scale` antes del tonemap: el tonemap en `gbrpf32le` trabaja a 1080×1920 en vez de a resolución de recorte 4K (≈3× menos trabajo, sin diferencia visible a 1080p).
- `-frames:v {n_frames}` cuenta frames de **salida** tras el filtergraph `[verificado: doc ffmpeg, opción output,per-stream]`.
- `-ss` de entrada + `-i`: seek exacto por defecto (`accurate_seek`), timestamps desde 0.
- `-fps_mode cfr` es redundante con `fps=30` y se pone como cinturón contra VFR accidental.
- Todos los segmentos comparten codec, perfil, pix_fmt, SAR, timescale, GOP y hilos → concat sin recodificar.

### 10.2 Segmento `blur_pad`

```bash
ffmpeg -y -ss {in_s} -t {t_safety} -i {src} \
  -filter_complex "[0:v]setpts=PTS/{speed},fps=30,\
scale='if(gt(iw,ih),-2,1080)':'if(gt(iw,ih),1080,-2)':flags=lanczos,{src_hdr}split[a][b];\
[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,\
boxblur={blur_radius}:{blur_power},eq=brightness={bg_brightness}[bg];\
[b]scale=1080:-2:flags=lanczos[fg];\
[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,format=yuv420p[v]" \
  -map "[v]" -fps_mode cfr -frames:v {n_frames} \
  (mismos flags de codec que 10.1) segments/seg_{slot:02d}.mp4
```

- Se reduce la fuente a 1080 en el lado corto antes de tonemap y `split`.
- `boxblur=20:2` por defecto (`40:8` = 8 pasadas de radio 40, lento sin ganancia visible).
- `effect_params` del clip suministra `blur_radius`, `blur_power`, `bg_brightness`.

### 10.3 Segmento de imagen

```bash
ffmpeg -y -framerate 30 -loop 1 -i {normalized_jpg} \
  -vf "crop={crop_px.w}:{crop_px.h}:{crop_px.x}:{crop_px.y},\
scale=3240:5760:flags=lanczos,\
zoompan=z='min(1.0+{zoom_per_frame}*(on-1),{zoom_max})':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1080x1920:fps=30,\
setsar=1,format=yuv420p" \
  -fps_mode cfr -frames:v {n_frames} \
  (mismos flags de codec que 10.1) segments/seg_{slot:02d}.mp4
```

- `zoompan` trunca el rectángulo de recorte a píxeles enteros de la fuente; a 1080 de ancho un zoom de 0.0015/frame avanza menos de un píxel por frame y produce jitter `[verificado: doc zoompan + fuentes secundarias]`. Por eso se pre-escala a 3240×5760 (3×) y `zoompan` emite 1080×1920. Ya no es un punto a validar.
- `on` es el contador acumulado de frames de salida y empieza en 1 `[verificado: lista ffmpeg-user]`; con `-loop 1` y `d=1` no se reinicia. `(on-1)` hace que el primer frame tenga zoom exactamente 1.0.
- Con `effect == none`: se elimina `zoompan` y el `scale` intermedio es `scale=1080:1920:flags=lanczos`.

### 10.4 Concat + audio (dos pasadas de loudnorm)

```bash
# segments.txt: una línea "file 'segments/seg_00.mp4'" por slot, en orden

# Pasada 1: medir (sobre el mismo WAV y el mismo tramo que se renderiza)
ffmpeg -t {duration_s} -i music/track_cut.wav \
  -af "loudnorm=I={target_lufs}:TP={target_tp}:LRA={target_lra}:print_format=json" -f null - 2> loudnorm_1.log
# parsear el JSON del log → input_i, input_tp, input_lra, input_thresh, target_offset → edl.audio.loudnorm_measured

# Pasada 2: render final
ffmpeg -y -f concat -safe 0 -i segments.txt \
  -t {duration_s} -i music/track_cut.wav \
  -map 0:v -map 1:a -c:v copy \
  -af "loudnorm=I={target_lufs}:TP={target_tp}:LRA={target_lra}:linear=true:\
measured_I={input_i}:measured_TP={input_tp}:measured_LRA={input_lra}:measured_thresh={input_thresh}:offset={target_offset}:print_format=json,\
aresample=48000,afade=t=out:st={duration_s - fade_out_s}:d={fade_out_s}" \
  -c:a aac -b:a 192k -ar 48000 -threads {threads} -movflags +faststart reel.mp4 2> loudnorm_2.log
# parsear el JSON de loudnorm_2.log → edl.audio.loudnorm_applied (debe traer normalization_type)
```

- `-c:v copy`: sin segunda generación de pérdidas.
- Entrada de audio = `track_cut.wav` sin `-ss`: es el mismo fichero sobre el que se detectaron los beats.
- `linear=true` exige los cuatro `measured_*` `[verificado: doc loudnorm]` y **cae en silencio a modo dinámico** si el LRA medido supera el objetivo o el TP no cabe `[verificado: fuente secundaria]`; por eso la pasada 2 también imprime JSON y R5 comprueba `normalization_type`.
- **Sin `-shortest`**: vídeo y audio tienen exactamente `duration_s` por construcción; `-shortest` introducía una carrera entre el último paquete de vídeo y el padding AAC que podía recortar el último frame.
- Con `audio.music_cut_path == null`: `ffmpeg -f concat -safe 0 -i segments.txt -c:v copy -an -movflags +faststart reel.mp4`.

### 10.5 Checks de render (R)

| # | Check | Cuándo | Acción si falla |
|---|---|---|---|
| R1 | `nb_read_frames(seg_NN) == n_frames` para cada segmento (final **y** preview) | tras cada segmento | error de render con el slot afectado |
| R2 | pHash del frame `{0, n/2, n−1}` de `segments/seg_NN` vs los mismos frames de `preview_segments/seg_NN` (ambos escalados a 256 de ancho): Hamming ≤ 8 en los tres `[validar umbral]` | tras cada segmento | error de render: tonemap, crop o tiempo del render final no coinciden con el proxy verificado |
| R3 | `nb_read_frames(reel.mp4) == duration_f`; duración de vídeo y de audio en `[duration_s − 1/30, duration_s + 1/30]` | tras concat | error |
| R4 | `color_primaries/transfer/space == bt709` y `color_range == tv` en segmentos y reel | tras concat | error (es tautológico con los flags; R2 es el check real de color) |
| R5 | `loudnorm_applied.normalization_type == "linear"` | tras concat | `warning: loudnorm_dynamic` (aceptar) si `config.allow_dynamic_loudnorm`, si no error |
| R6 | DTS y PTS de vídeo estrictamente monótonos en `reel.mp4` (`ffprobe -show_packets`), sin huecos > 1 frame | tras concat | error: el concat con `-c:v copy` ha dejado un salto; re-encodear el reel como fallback (`warning: concat_reencoded`) |

---

## 11. Modelo y coste

- **Modelo por defecto:** `gemini-3.7-flash`. `gemini-3.8-flash` existe (2/9/2026) y cuesta lo mismo: $0.75 / 1M entrada y $3.75 / 1M salida hasta 31/12/2026; después $1.50 / $7.50 `[verificado: cloud.google.com pricing]`. Fuentes secundarias indican que 3.8 gasta más tokens de thinking y que Google recomienda 3.7 para cargas orientadas a eficiencia `[no verificado en fuente primaria]`; para este uso (selección entre candidatos) se parte de 3.7 y se compara en Sesiones 4–7. Ambos: `thinking_level ∈ {low, medium, high}`, ventana 1M tokens, salida máx. 64k; los tokens de thinking se facturan como salida.
- **API:** Interactions API (`client.interactions.create`) con `response_format.schema`. Los parámetros `response_schema` / `response_json_schema` de `generateContent` no se usan.
- **Coste por Reel (modo imágenes, `low`):** ≈ 90 imágenes × 280 = 25k tokens + prompt ≈ 2k → ≈ $0.02 de entrada; salida ≈ 1.5k + thinking (2–6k en `low`) ≈ $0.01–0.03. Total ≈ $0.03–0.05 `[validar leyendo usage en la primera sesión]`. Sin `resolution: low` la entrada sube a ≈ 101k tokens (≈ $0.08).
- **Coste por Reel (modo vídeo, opcional):** 70 tokens/frame en `low`/`medium`. Ventanas de 4 s a 2 fps × 30 candidatos sin audio ≈ 17k tokens; a 1 fps ≈ 8k. Más barato que imágenes.
- **Files API** (solo modo vídeo): gratis, 48 h de retención, 20 GB/proyecto, 2 GB/fichero; el mismo `uri` se reutiliza en los reintentos.
- Se registra `usage` de cada llamada en `log.jsonl`, `provenance.llm_usage` y `provenance.llm_cost_usd`.

---

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

---

## 13. Riesgos abiertos

- **Umbrales de CV** (`sharpness`, `kp_speed`, `motion_bg`, prominencia, `calm`): calibrar con material real; guardar histogramas por sesión y las hojas de contacto de todos los candidatos.
- **Tonemap HLG/DV:** decidir zscale vs libplacebo en Sesión 0; validar en pantalla de móvil; `npl` para HLG en zimg sin fuente primaria.
- **Tracking:** YOLO-pose en CPU a 10 fps sobre 720p `[validar tiempo por clip]`; con keypoints ruidosos `kp_speed` puede picar en falsos positivos (oclusiones); alternativa: suavizado más agresivo o `yolov8s-pose`.
- **ContentDetector con whip pans:** falsos cortes que reducen ventanas; contar cortes por clip.
- **Verificación temporal (§4.4):** el margen `d_0 < min(d_±1)` puede no cumplirse en movimientos lentos aunque el alineamiento sea correcto; si genera falsos negativos, relajar a `argmin_k == 0` con `d_0 ≤ 6`.
- **Concat `-c:v copy`:** posibles avisos "Non-monotonous DTS" por edit lists de segmentos con B-frames; R6 lo detecta y el fallback re-encodea.
- **Derechos de música:** el pipeline renderiza con `music_cut_path = null` y `-an`.
- **SDK de Gemini:** nombre del campo de imagen inline con `resolution` y parámetro `processing` de vídeo `[validar contra la versión instalada]`; el resto de nombres está verificado.
- **Evaluación:** sin dataset de referencia "funciona" es anecdótico; ver §14.

---

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
