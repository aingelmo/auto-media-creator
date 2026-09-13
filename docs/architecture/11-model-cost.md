[← README](README.md)

## 11. Modelo y coste

- **Modelo por defecto:** `gemini-3.7-flash`. `gemini-3.8-flash` existe (2/9/2026) y cuesta lo mismo: $0.75 / 1M entrada y $3.75 / 1M salida hasta 31/12/2026; después $1.50 / $7.50 `[verificado: cloud.google.com pricing]`. Fuentes secundarias indican que 3.8 gasta más tokens de thinking y que Google recomienda 3.7 para cargas orientadas a eficiencia `[no verificado en fuente primaria]`; para este uso (selección entre candidatos) se parte de 3.7 y se compara en Sesiones 4–7. Ambos: `thinking_level ∈ {low, medium, high}`, ventana 1M tokens, salida máx. 64k; los tokens de thinking se facturan como salida.
- **API:** Interactions API (`client.interactions.create`) con `response_format.schema`. Los parámetros `response_schema` / `response_json_schema` de `generateContent` no se usan.
- **Coste por Reel (modo imágenes, `low`):** ≈ 90 imágenes × 280 = 25k tokens + prompt ≈ 2k → ≈ $0.02 de entrada; salida ≈ 1.5k + thinking (2–6k en `low`) ≈ $0.01–0.03. Total ≈ $0.03–0.05 `[validar leyendo usage en la primera sesión]`. Sin `resolution: low` la entrada sube a ≈ 101k tokens (≈ $0.08).
- **Coste por Reel (modo vídeo, opcional):** 70 tokens/frame en `low`/`medium`. Ventanas de 4 s a 2 fps × 30 candidatos sin audio ≈ 17k tokens; a 1 fps ≈ 8k. Más barato que imágenes.
- **Files API** (solo modo vídeo): gratis, 48 h de retención, 20 GB/proyecto, 2 GB/fichero; el mismo `uri` se reutiliza en los reintentos.
- Se registra `usage` de cada llamada en `log.jsonl`, `provenance.llm_usage` y `provenance.llm_cost_usd`.


