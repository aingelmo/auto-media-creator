[← README](README.md)

## 9. Capa 6 — Preview

Mismo código de render (Capa 7) sobre los proxies, **por segmento**, salida 540×960, `-preset ultrafast -crf 30`, sin loudnorm (solo `volume`). Se genera **siempre**: los segmentos de preview son la referencia de los checks R2 (§10.5). El `preview.mp4` concatenado es obligatorio revisar cuando hay W1–W5 o `planner != llm`; recomendado siempre en las primeras 10 sesiones. Los `in_s/out_s` son válidos tal cual sobre el proxy (misma convención de tiempo, verificada en §4.4). El crop en píxeles del preview se recalcula desde `crop` normalizado con las dims del proxy (misma regla de §6.5).


