[← README](README.md)

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


