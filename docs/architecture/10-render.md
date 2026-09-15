[← README](README.md)

## 10. Capa 7 — Render

Todos los comandos llevan `-threads {threads}` y los flags exactos se serializan en `render_profile`.

### 10.1 Segmento de vídeo (`layout == crop`)

```bash
# {src_hdr}: render_profile.tonemap_chain seguida de coma, o vacío si hdr == none
# {t_safety} = out_s - in_s + 0.5   (solo tope de lectura; el corte exacto lo da -frames:v)
ffmpeg -y -ss {in_s} -t {t_safety} -i {src} \
  -vf "crop={crop_px.w}:{crop_px.h}:{crop_px.x}:{crop_px.y},\
setpts={setpts},fps=30,\
scale=1080:1920:flags=lanczos,\
{src_hdr}{color_fix}setsar=1,format=yuv420p" \
  -fps_mode cfr -frames:v {n_frames} \
  -color_primaries bt709 -color_trc bt709 -colorspace bt709 -color_range tv \
  -an -c:v libx264 -crf 18 -preset medium -profile:v high -pix_fmt yuv420p \
  -video_track_timescale 30000 -g 60 -keyint_min 60 -sc_threshold 0 -threads {threads} \
  segments/seg_{slot:02d}.mp4
```

- `{color_fix}`: si el clip trae `color_fix` (§6.7), `eq=brightness={brightness}:saturation={saturation},colorcorrect=rl={rl}:bl={bl}:rh={rl}:bh={bl},`; si no, vacío. Igual en preview y final (`render_profile.color_fix_filter_template`).
- `{text}` (`render/_common.py:hook_text_filter`): si `effect_params.text` existe, `drawtext=fontfile='{font}':expansion=none:text={text}:fontsize={size}:fontcolor=white:borderw={border}:bordercolor=black@0.6:x=(w-text_w)/2:y={y}:alpha='if(lt(n,{fade}),n/{fade},if(lt(n,{end}-{fade}),1,if(lt(n,{end}),({end}-n)/{fade},0)))',`; si no, vacío. `size`, `border` e `y` se escalan por `target.w/1080`; `n` es el índice de frame tras `fps=30`. El texto va **sin comillas** y escapado dos veces (`_drawtext_escape`: `\ : '` para el parser de opciones, luego `\ ' , ; [ ]` para el del filtergraph) porque dentro de comillas simples el filtergraph no procesa escapes. Va después de `{color_fix}` para que la corrección no tiña el blanco. Igual en preview y final (`render_profile.hook_text_filter_template`, `hook_text_font_sha256`).
- Orden del filtro: `crop` (reduce píxeles) → `setpts` (velocidad) → `fps` (fija cadencia **después** de la velocidad) → `scale` → tonemap → `{color_fix}` → `{text}` → `setsar`.
  - `{setpts}` (`render/_common.py:setpts_expr`): sin rampa, `PTS/1.0` (no-op). Con `effect == ramp`, la expresión a trozos `render_profile.ramp_setpts_template`, con `t_a = ramp_start_f/30`, `t_b = t_a + ramp_frames/30·ramp_speed` en segundos de **entrada** (`T` arranca en 0 tras `-ss`):
    `'if(lt(T,t_a),PTS,if(lt(T,t_b),(t_a+(T-t_a)/s)/TB,(t_a+n/30+(T-t_b))/TB))'`. Las comillas simples protegen las comas del parser del filtergraph.
  - `fps=30` tras `setpts` remuestrea: en la ventana lenta duplica frames (fuente 30 fps) o los conserva (fuente 60 fps). Se consumen `out_s − in_s` s de fuente y se emiten `d_f` frames, coherente con §6.3. **El orden inverso (`fps` antes de `setpts`) rompe la cuenta de frames y hace fallar R1**; no usar.
  - `scale` antes del tonemap: el tonemap en `gbrpf32le` trabaja a 1080×1920 en vez de a resolución de recorte 4K (≈3× menos trabajo, sin diferencia visible a 1080p).
- `-frames:v {n_frames}` cuenta frames de **salida** tras el filtergraph `[verificado: doc ffmpeg, opción output,per-stream]`.
- `-ss` de entrada + `-i`: seek exacto por defecto (`accurate_seek`), timestamps desde 0.
- `-fps_mode cfr` es redundante con `fps=30` y se pone como cinturón contra VFR accidental.
- Todos los segmentos comparten codec, perfil, pix_fmt, SAR, timescale, GOP y hilos → concat sin recodificar.

### 10.2 Segmento `blur_pad`

```bash
ffmpeg -y -ss {in_s} -t {t_safety} -i {src} \
  -filter_complex "[0:v]setpts={setpts},fps=30,\
scale='if(gt(iw,ih),-2,1080)':'if(gt(iw,ih),1080,-2)':flags=lanczos,{src_hdr}{color_fix}split[a][b];\
[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,\
boxblur={blur_radius}:{blur_power},eq=brightness={bg_brightness}[bg];\
[b]scale=1080:-2:flags=lanczos[fg];\
[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,format=yuv420p[v]" \
  -map "[v]" -fps_mode cfr -frames:v {n_frames} \
  (mismos flags de codec que 10.1) segments/seg_{slot:02d}.mp4
```

- Se reduce la fuente a 1080 en el lado corto antes de tonemap y `split`. `{color_fix}` va antes del `split` para que fondo y primer plano reciban la misma corrección.
- `boxblur=20:2` por defecto (`40:8` = 8 pasadas de radio 40, lento sin ganancia visible).
- `effect_params` del clip suministra `blur_radius`, `blur_power`, `bg_brightness`.

### 10.3 Segmento de imagen

```bash
ffmpeg -y -framerate 30 -loop 1 -i {normalized_jpg} \
  -vf "crop={crop_px.w}:{crop_px.h}:{crop_px.x}:{crop_px.y},\
scale=3240:5760:flags=lanczos,\
zoompan=z='min(1.0+{zoom_per_frame}*(on-1),{zoom_max})':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1080x1920:fps=30,\
{color_fix}setsar=1,format=yuv420p" \
  -fps_mode cfr -frames:v {n_frames} \
  (mismos flags de codec que 10.1) segments/seg_{slot:02d}.mp4
```

- `zoompan` trunca el rectángulo de recorte a píxeles enteros de la fuente; a 1080 de ancho un zoom de 0.0015/frame avanza menos de un píxel por frame y produce jitter `[verificado: doc zoompan + fuentes secundarias]`. Por eso se pre-escala a 3240×5760 (3×) y `zoompan` emite 1080×1920. Ya no es un punto a validar.
- `on` es el contador acumulado de frames de salida y empieza en 1 `[verificado: lista ffmpeg-user]`; con `-loop 1` y `d=1` no se reinicia. `(on-1)` hace que el primer frame tenga zoom exactamente 1.0.
- Con `effect == none`: se elimina `zoompan` y el `scale` intermedio es `scale=1080:1920:flags=lanczos`; `{color_fix}` sigue justo antes de `setsar`.

### 10.6 Capa de marca (§6.8)

- Los tres renderers (10.1–10.3) usan ya `-filter_complex` con la cadena principal como `[0:v]…` y cierran con `_common.finish_graph`: sin marca, `…setsar=1,format=yuv420p[v]`; con `edl.brand.watermark`, el logo entra como segundo input (`-i brand/logo.png`) y la cola es `[v0];[1:v]scale={lw}:-1:flags=lanczos,format=rgba,colorchannelmixer=aa={opacity}[lg];[v0][lg]overlay=W-w-{inset}:H-h-{bottom}:format=auto,setsar=1,format=yuv420p[v]`, con `lw`, `inset` escalados por `target.w/1080` y `bottom = bottom_frac·target.h`. Va después de `color_fix` y del texto del hook.
- **End card** (`effect == end_card`, `render_end_card_segment`): `-f lavfi -i color=c={bg}:s={tw}x{th}:r=30 -i {logo}` + `[1:v]scale={lw}:-1[lg];[0:v][lg]overlay=(W-w)/2:(H-h)/2-{1.5·ts}[v1];[v1]drawtext(handle),drawtext(line, 0.7·ts, fg@0.8),fade=t=in:st=0:d=0.25,setsar=1,format=yuv420p[v]` con `-frames:v n_frames`. Sin watermark sobre la card. Preview y final usan el mismo grafo con tamaños escalados, así que R1/R2 aplican igual.

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


