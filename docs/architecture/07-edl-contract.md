[← README](README.md)

## 7. Contrato EDL v5 (`edl.json`, lo genera código)

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
          "speed": { "type": "number", "const": 1.0 },
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
          "effect": { "type": "string", "enum": ["none", "kenburns", "ramp", "end_card"] },
          "effect_params": { "type": "object", "description": "Con clave `text` (+ font, font_size, text_y, text_frames, fade_frames) el render sobreimprime el hook_line del selector (§6.6). Con `punch_frames`/`punch_zoom` (develop) o `flash_frame`/`flash_frames` (hook) el render aplica el punch-in o el flash blanco del corte (§6.6). El close con marca lleva `outro_*` (outro_frames, outro_fg, outro_font, outro_handle, outro_logo_src, outro_logo_w, outro_logo_h, outro_text_size, outro_blur_radius, outro_blur_power, outro_dim): el render difumina/oscurece solo su cola y sobreimprime logo + handle (§6.8)" },
          "color_fix": {
            "type": "object",
            "description": "Opcional (§6.7). Ausente => sin igualación de color, render idéntico a v4 previo",
            "properties": {
              "brightness": { "type": "number", "minimum": 0, "maximum": 0.15 },
              "saturation": { "type": "number", "minimum": 0.85, "maximum": 1.15 },
              "rl": { "type": "number", "minimum": -0.1, "maximum": 0.1 },
              "bl": { "type": "number", "minimum": -0.1, "maximum": 0.1 },
              "measured": { "type": "object" }
            },
            "required": ["brightness", "saturation", "rl", "bl"]
          },
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
        "fade_out_s": { "type": "number", "minimum": 0 },
        "sfx": {
          "type": "array",
          "description": "Sonido diegético del hook y de los clips peak, mezclado bajo la música a `gain_db` fijo (idea #5). Autocontenido: no referencia `clips`.",
          "items": {
            "type": "object",
            "properties": {
              "slot": { "type": "integer" },
              "src": { "type": "string" },
              "in_s": { "type": "number", "minimum": 0 },
              "dur_s": { "type": "number", "minimum": 0 },
              "delay_ms": { "type": "integer", "minimum": 0 },
              "gain_db": { "type": "number" },
              "ramp": {
                "type": ["object", "null"],
                "properties": {
                  "start_f": { "type": "integer" },
                  "frames": { "type": "integer" },
                  "speed": { "type": "number" }
                },
                "required": ["start_f", "frames", "speed"]
              }
            },
            "required": ["slot", "src", "in_s", "dur_s", "delay_ms", "gain_db", "ramp"]
          }
        }
      },
      "required": ["music_cut_path", "music_cut_sha256", "music_src_path", "music_src_sha256", "music_offset_s", "target_lufs", "target_tp", "target_lra", "loudnorm_measured", "loudnorm_applied", "fade_out_s", "sfx"]
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

Cambios frente a v5 (v6): desaparecen `role`/`effect` `end_card` y el clip sintético — la marca de cierre es un tratamiento `outro_*` sobre la cola del close que nunca se salta (§6.8); `render_profile` añade `outro_filter_template` (`end_card_filter_template` se conserva solo para re-renderizar EDLs v5 antiguas).

Cambios frente a v4 (v5): `effect` admite `end_card` y `role` admite `end_card` (clip sintético que toma los últimos frames del close, §6.8); nuevo top-level opcional `brand` (`logo` relativo a la sesión, `logo_sha256`, `logo_w`, `logo_h`, `handle`, `bg`, `fg`, `font`, `watermark: {w, opacity, inset_x, bottom_frac} | null`) o `null`; `render_profile` añade `logo_filter_template`, `end_card_filter_template`, `brand_sha256`. `speed` es siempre 1.0 desde el ramp (§6.3). Aditivo, sigue v5: `audio.sfx[]` (sonido diegético del hook/peak bajo la música, idea #5) y `render_profile.sfx_filter_template`.

Cambios frente a v3: `render_profile` (versiones, configuración de FFmpeg, hilos, cadenas y flags exactos, hash); `crop_px`, `src_rotation`, `src_color`, `effect`/`effect_params` por clip; `music_cut_*` y `music_src_*` con hashes; `target_tp/target_lra`; `loudnorm_applied`; `sdk_version`, `api_revision`, `llm_usage`; hashes de config de features y del modelo de pose. `audio.music_cut_path = null` es válido y produce un render con `-an` (derechos de música). Este schema se valida localmente con `jsonschema` (draft-07 sí soporta `const` y `exclusiveMinimum`); **no se envía a Gemini**.


