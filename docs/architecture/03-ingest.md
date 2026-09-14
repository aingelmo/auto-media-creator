[← README](README.md)

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
zscale=tin=arib-std-b67:t=linear:npl=203,format=gbrpf32le,zscale=p=bt709,tonemap=hable:desat=0,\
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
- `npl=203` con HLG: blanco de referencia HLG (BT.2408). Con `npl=1000` los clips DV84 salían a Y≈62 frente a Y≈110 de los SDR de la misma escena; con 203 quedan en Y≈100-127 (medido 2026-09-15). Alternativa no adoptada, `libplacebo`:
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


