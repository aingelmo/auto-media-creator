[← README](README.md)

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


