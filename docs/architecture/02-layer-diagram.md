[← README](README.md)

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


