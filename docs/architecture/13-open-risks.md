[← README](README.md)

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


