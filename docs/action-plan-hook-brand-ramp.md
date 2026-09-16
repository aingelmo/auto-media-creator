# Action plan: hook text, brand layer, speed ramp

Executable plan for items 1–3 of `ideas-to-imrpove.md`. Written to be handed to an implementer with no prior context on the repo. Read `docs/architecture/06-planner.md`, `07-edl-contract.md`, `10-render.md` first.

## Ground rules (apply to all three features)

- **No new dependencies.** Everything is ffmpeg filters (`drawtext`, `overlay`, `movie`, `setpts`) already present in the installed ffmpeg (verified: `ffmpeg -filters` lists `drawtext` with libfreetype).
- **Segments stay independent.** Every effect lives *inside* a segment's filtergraph so `concat -c:v copy` (`render/concat.py`) is untouched. Never use `xfade`.
- **Preview and final must match.** `render_segment()` in `render/segments.py` renders both from the same clip dict; R2 (`render/checks.py:check_r2_phash`) compares pHash of frames 0, n/2, n-1 at 256 px wide. Any new filter must be applied identically in `preview=True` and `preview=False`, with pixel sizes scaled by `target["w"] / 1080`.
- **Frame count is law.** `-frames:v n_frames` + P5/P6 invariants (`planner/invariants.py`). Nothing may change `n_frames`.
- **EDL is the contract.** All parameters go into `clip.effect_params` (or a new top-level `edl["brand"]`) at planner time; render only reads the EDL. `render/profile.py:get_render_profile` must include every new filter template string so `profile_sha256` changes when the filter changes.
- **Config lives in `planner/_common.py:DEFAULT_CONFIG`**, plumbed through `session/planner.py:run_planner(config=...)`. Web UI (`web/pipeline.py:run_pipeline_job`) currently passes no planner config; add a `planner_config: dict` argument there and to `scripts/run_e2e.py`.
- **Tests:** extend `tests/test_render.py` (hand-written EDL, synthetic `life=` clips, no CV/LLM) and `tests/test_planner.py`. Run `uv run ruff check . && uv run ty check && uv run pytest -q` after each step.
- **Docs:** update `docs/architecture/06-planner.md` (§6.6), `07-edl-contract.md` (schema), `10-render.md` (filters). Bump `edl.VERSION` to 5 once, at the end, since `effect_params`/top-level keys change.

Recommended order: **3 → 1 → 2**. The ramp changes the planner timing math, which the other two do not touch, so land it first while the timing code is fresh. Each step is independently shippable.

---

## Step 3 — Speed ramp on the peak (do first)

### Goal
Hook clip plays at 1.0x, slows to `ramp_speed` (default 0.4) in a window of `ramp_frames` output frames (default 12) centred on the beat where the peak lands, then snaps back to 1.0x. Replaces the current flat `hook_speed = 0.5`.

### Current behaviour to understand
- `planner/timing.py:compute_in_out` computes `need_s = d_f / 30 * speed` seconds of source for `d_f` output frames and places `t_peak` at `lead_f = beats_rel_f[peak_beat_index]` (output frames from slot start).
- `planner/pipeline.py:build_clips` sets `speed = config["hook_speed"]` for the hook, 1.0 elsewhere.
- `render/segments.py` emits `setpts=PTS/{speed},fps=30` then `-frames:v n_frames`.
- P5 asserts `round((out_s - in_s) / speed * 30) == n_frames`.
- `edl._aggregate_warnings` emits `slowmo_duplicates` when hook speed is 0.5 on a ≤30 fps source.

### Design
Piecewise-linear ramp expressed in **output frames**:

```
output frame k in [0, d_f)
  region A: k <  a          → speed 1.0      (a = lead_f - ramp_frames/2)
  region B: a ≤ k < b       → speed s        (b = a + ramp_frames)
  region C: k ≥ b           → speed 1.0
source seconds consumed = (a + (d_f - b)) / 30 + ramp_frames / 30 * s
```

Keep it a hard step (no easing). Easing looks smoother but needs an integral expression in `setpts`; add later if wanted.

`setpts` maps *input* timestamps to output; the input-time breakpoints are:

```
t_a = a / 30                       # source seconds until ramp starts
t_b = t_a + ramp_frames / 30 * s   # source seconds where ramp ends
setpts='if(lt(T,t_a), PTS, if(lt(T,t_b), (t_a + (T - t_a)/s)/TB, (t_a + ramp_frames/30 + (T - t_b))/TB))'
```

`T` is input time in seconds after `-ss` (starts at 0 because `-ss` is an input option). `fps=30` after `setpts` then samples at 30 Hz, so a 60 fps source gives true slow motion and a 30 fps source duplicates frames (same as today with 0.5x).

### Changes

1. **`planner/_common.py:DEFAULT_CONFIG`**
   - Remove `hook_speed` (keep reading it for one release only if you want back-compat; simpler: remove and update tests).
   - Add `"hook_ramp": True`, `"ramp_speed": 0.4`, `"ramp_frames": 12`.

2. **`planner/timing.py:compute_in_out`**
   - New signature: replace `speed: float` with `ramp: dict | None` where `ramp = {"speed": s, "frames": n}` or `None`.
   - When `ramp` is set and `kind == "peak"` and `len(beats) >= 2`:
     ```
     a = max(0, lead_f - n // 2); b = min(d_f, a + n); n_eff = b - a
     need_s = (d_f - n_eff) / 30 + n_eff / 30 * s
     lead_src_s = a / 30 + (lead_f - a) / 30 * s     # source seconds from in_s to the peak
     raw_in_s = t_peak - lead_src_s
     ```
     Clamp exactly as today. Return additionally `"ramp": {"speed": s, "frames": n_eff, "start_f": a}` (use `n_eff` so an edge-clamped ramp stays consistent). When ramp is not applicable, return `"ramp": None` and the current 1.0x maths.
   - `speed` field in the clip becomes always `1.0`; the ramp is in `effect_params`.

3. **`planner/effects.py:effect_for`**
   - Accept `ramp: dict | None`. If set, return `("ramp", {"ramp_speed": s, "ramp_frames": n_eff, "ramp_start_f": a})`. Note `effect` is currently `"kenburns" | "none"`; add `"ramp"`. A hook is never an image so there is no collision with Ken Burns. `blur_pad` params can coexist: merge dicts (`{**blur_params, **ramp_params}`) and keep `effect="ramp"`.

4. **`planner/pipeline.py:build_clips`**
   - `per_slot[hook] = (assignment.hook, "hook", ramp_cfg)` where `ramp_cfg = {"speed": config["ramp_speed"], "frames": config["ramp_frames"]} if config["hook_ramp"] else None`.
   - Pass `timing["ramp"]` into `effect_for`.

5. **`planner/invariants.py` P5**
   - If `c["effect"] == "ramp"`: `expected = round((out_s - in_s - n_eff/30*s) * 30) + n_eff`. Otherwise unchanged.

6. **`planner/assignment.py`** – admission uses `admits(window, d_f, speed)`. With a ramp the clip needs *less* source than 1.0x, so admitting at speed 1.0 is conservative and correct. No change needed; add a comment.

7. **`render/segments.py:render_video_segment`**
   - Build `pts_expr = _setpts_expr(clip)`: returns `"PTS/1.0"` when no ramp, else the `if()` expression above with `t_a`, `t_b`, `s`, `ramp_frames` substituted. Put it in `render/_common.py` next to `color_fix_filter` so `profile.py` can import the template.
   - Replace `setpts=PTS/{speed}` with `setpts='{pts_expr}'` in both the `crop` and `blur_pad` graphs. Keep `fps=30` immediately after.
   - `t_safety` stays `(out_s - in_s) + 0.5`. Replace the `n_frames/30*speed` formula with `clip["out_s"] - clip["in_s"] + 0.5`; it is equivalent today and correct with ramps.
   - Escape commas inside the expression: filtergraph splits on `,`, so wrap the whole `setpts=` value in single quotes (already done above) and use `\,` if you need commas inside; the expression uses only `if(…)` with commas → write `setpts='if(lt(T\,{t_a})\,PTS\,…)'`. Test in a shell first.

8. **`render/profile.py`** – add `"ramp_setpts_template"` with the raw expression string; update `segment_filter_template` and `blur_pad_filter_template` to show `setpts='{pts}'`.

9. **`edl.py:_aggregate_warnings`** – `slowmo_duplicates`: trigger when `hook["effect"] == "ramp"` and `src_fps_nominal <= 30`. The message meaning is unchanged.

10. **`edl.py`** – schema doc says `speed enum [0.5, 1.0]`; keep the field (always 1.0 now) so the EDL stays backward-readable. Note it in 07.

### Tests
- `tests/test_planner.py`: new `test_compute_in_out_ramp_peak_on_beat` — with `ramp={"speed":0.4,"frames":12}`, `d_f=45`, `lead_f=15`: assert `need_s == (45-12)/30 + 12/30*0.4`, `in_s == t_peak - (9/30 + 6/30*0.4)`, `ramp["start_f"] == 9`.
- `tests/test_planner.py:test_planner_invariants` — run once with `hook_ramp=True` and confirm `assert_invariants` passes.
- `tests/test_render.py`: extend the existing e2e (`test_render_e2e_hook_slowmo_and_deterministic_rerender`): make the hook clip `effect="ramp"`, `effect_params={"ramp_speed":0.4,"ramp_frames":12,"ramp_start_f":9}`, `speed=1.0`, `in_s/out_s` per the formula, and assert R1 (frame count exact), R2 (preview↔final), R6 pass. Also run `ffprobe -show_frames` on the segment and assert the frame at index `ramp_start_f + 6` differs from the one at `ramp_start_f + 5` less than frames outside the ramp (sanity that motion slowed); or skip this and rely on eyeballing.
- Manual: render a real session, scrub the hook in the web UI, check the slow part sits on the beat.

### Ceilings to note in code (`# ponytail:` comments)
- Hard-step ramp; add `easing` (quadratic in `setpts`) if it looks abrupt.
- Ramp only on the hook. Making it per-develop is just passing `ramp_cfg` to more slots; do not do it yet, it makes the reel feel slow.

---

## Step 1 — Hook text overlay

> Superseded 2026-09-15 by the hook-choice flow (see `docs/architecture/05-selector-llm.md` §5.7): the single selector-LLM `hook_line` described below no longer exists. Hook lines now come from a separate LLM call generating 6 lines/angles into `hooks.json`, with an operator pick step (`hook_choice` pause) in the web UI. The text-overlay rendering mechanics below (fade timing, `effect_params`, `_drawtext_escape`) are still accurate.
> Superseded again 2026-09-16 (see `docs/architecture/05-selector-llm.md` §5.7): the copy call no longer generates 6 lines/angles; it's one evidence-anchored line (or an abstention), verified in code against `{candidate_id, evidence}`.
> Superseded again 2026-09-16 (see `docs/architecture/05-selector-llm.md` §5.7): the copy call is context-aware again — it takes an operator brief, an audience (`prospects`/`members`), and a text summary of the whole selection, and returns exactly 3 lines, one per fixed angle (`contexto`/`afirmacion`/`adelanto`), each independently validated against `{candidate_id, evidence, hooks}`.

### Goal
A short Spanish hook line (3–6 words) written by the selector LLM, burned into the hook segment: large, centred horizontally, in the upper-middle safe zone, fades in over 8 frames at frame 0 and fades out over 8 frames ending at `min(hook_n_frames, 60)`. Off by default for `theme == "yoga"`? No: on for both, the LLM writes a theme-appropriate line.

### Changes

1. **`selector/prompts.py`**
   - `selection_schema()`: add top-level `"hook_line": {"type": "string", "description": "Frase gancho para el primer segundo del Reel, en español, 3–6 palabras, mayúsculas iniciales, sin emojis ni comillas. Concreta y visual: qué se ve, no un eslogan genérico."}` and add it to `required`.
   - `SYSTEM_PROMPT_TEMPLATE`: add rule 6: `hook_line: una frase de 3–6 palabras para sobreimprimir en el hook. Debe describir lo que se ve en el candidato hook (ejercicio, intensidad, momento), no el gimnasio. Ejemplos: "Último rep, sin excusas", "140 kg y sube", "Así empieza el lunes".` Keep it under 3 lines of prompt.
   - `THEMES[...]`: optionally add a `hook_line` hint per theme (training: energetic; yoga: calm). One line each.
   - `REINFORCED_SUFFIX`: append `hook_line: máximo 6 palabras.`

2. **`selection/s_checks.py:apply_s_checks`** – currently returns `(cleaned_entries, warnings)` and drops the top-level. Add a cheap sanitiser (no new function file): `hook_line = selection.get("hook_line", "").strip()[:40]`; strip surrounding quotes; if `len(hook_line.split()) > 8` or empty → `""` and warning `"hook_line_invalid"`. Return it as a third element or attach it to the hook entry as `entry["hook_line"]`. **Recommended: attach to the hook entry**, because `build_selected` → `assign_slots` → `assignment.hook` already flows to the planner untouched; no signature churn. Fallback hook entries (`selection/fallback.py`) get `"hook_line": ""`.

3. **`planner/_common.py:DEFAULT_CONFIG`** – add:
   ```
   "hook_text": True,
   "hook_text_font": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  # present on this machine; make it a config value, not a constant
   "hook_text_size": 88,        # px at 1080 wide
   "hook_text_y": 0.28,         # fraction of height, top of text box (inside the Reels safe zone)
   "hook_text_max_frames": 60,
   "hook_text_fade_frames": 8,
   ```

4. **`planner/effects.py:effect_for`** – accept the selection entry too (or just `hook_line: str`). If role is hook, `config["hook_text"]` and `hook_line` non-empty: add to `effect_params`: `{"text": hook_line, "font": …, "font_size": …, "text_y": …, "text_frames": min(max_frames, d_f), "fade_frames": …}`. Do **not** change `effect` (it may be `"ramp"`); presence of `effect_params["text"]` is the switch. Update the docstring.

5. **`render/_common.py`** – add:
   ```
   HOOK_TEXT_FILTER_TEMPLATE = (
       "drawtext=fontfile='{font}':text='{text}':fontsize={size}:fontcolor=white:"
       "borderw={border}:bordercolor=black@0.6:"
       "x=(w-text_w)/2:y={y}:"
       "alpha='if(lt(n,{fade}),n/{fade},if(lt(n,{end}-{fade}),1,if(lt(n,{end}),({end}-n)/{fade},0)))',"
   )
   def hook_text_filter(clip, target) -> str
   ```
   - `scale = target["w"] / 1080`; `size = round(font_size * scale)`, `border = max(2, round(4 * scale))`, `y = round(text_y * target["h"])`.
   - Escape the text for drawtext: replace `\` → `\\\\`, `'` → `\\'`, `:` → `\\:`, `%` → `%%`. Put this in one small `_drawtext_escape(s)` helper and unit-test it.
   - Note `n` in drawtext is the output frame counter of the filter, which after `fps=30` equals the segment frame index. Place the filter **after** `fps=30` and after `scale` (so text is drawn at target resolution), right before `{color_fix}`? No: **after** `{color_fix}`, so the colour correction does not tint the white text. Order: `…scale,{hdr}{color_fix}{hook_text}setsar=1,format=yuv420p`.
   - For `blur_pad`: apply on the final composited stream: `[bg][fg]overlay=…,{hook_text}setsar=1,…`.

6. **`render/profile.py`** – add `"hook_text_filter_template": HOOK_TEXT_FILTER_TEMPLATE` and the font path/sha256 (`hashlib.sha256(Path(font).read_bytes())`, guarded if the file is missing) so a font change alters `profile_sha256`.

7. **R2 note** – text is rendered at both resolutions with proportionally scaled size; pHash at 256 px wide should stay within the threshold. If R2 fails on the hook segment only because of anti-aliasing differences, raise the R2 threshold for clips with `effect_params.get("text")` to 12, not globally.

8. **Web UI** – `web/templates/session.html` debug view: show `selection.json.hook_line` (or the hook entry's `hook_line`) next to the hook candidate so the operator sees the line before render. Optional: a text input on the regenerate form to override it (`planner_config["hook_line_override"]`); skip unless trivially available.

### Tests
- `tests/test_selector.py`: schema includes `hook_line` in `required`; prompt contains `hook_line`.
- `tests/test_selection.py`: `apply_s_checks` with `hook_line="  \"Sube el peso\" "` → hook entry gets `Sube el peso`; with 12 words → `""` + `hook_line_invalid` warning; missing key → `""` no warning.
- `tests/test_render.py`: add a `_drawtext_escape` unit test (`"100% real: it's"` → `"100%% real\\: it\\'s"`), and extend the e2e hook clip with `effect_params["text"]="Prueba"`; assert R1/R2 pass and the segment renders (ffmpeg would fail loudly on a bad `drawtext` string).
- Manual: view on a phone. Text must sit above the Reels caption/UI overlay (bottom ~ 320 px) and below the top bar (~ 200 px). `text_y = 0.28` → y = 538 px, OK.

### Skip for now
- Word-wrapping: constrain the prompt to ≤ 6 words at 88 px; `drawtext` does not wrap. If a line is wider than 1000 px it will clip; add `text_shaping`/manual `\n` insertion only if it happens.
- Animated text (slide, kinetic): fade is enough.

---

## Step 2 — Brand layer (logo watermark + end card)

### Goal
- **Watermark:** PNG logo with alpha, bottom-right of every segment, `logo_w = 160 px` wide at 1080, 60% opacity, inset 48 px, but raised to clear the Reels UI: `y = h - logo_h - 340` at 1080×1920 (fraction: `0.177 * h`).
- **End card:** last `end_card_frames` (default 45 = 1.5 s) of the reel show a full-frame brand card: solid background colour + centred logo (large) + one text line (handle/address). The card **takes its frames from the close slot** so `duration_f` and the music cut are unchanged: close clip becomes `d_close - 45` frames, and a new synthetic clip `role="end_card"` fills the last 45 frames. If `d_close - 45 < 30` (P9), shrink the card to `d_close - 30`; if that is `< 15`, skip the card and warn `end_card_skipped`.

### Inputs
- `brand/logo.png` and `brand/brand.json` in the **repo root** (`brand/` dir, gitignored contents except a README) OR per session under `sessions/<name>/brand/`. Recommended: repo-level default at `brand/`, overridable per session by copying into `sessions/<name>/brand/`. `brand.json`:
  ```json
  {"logo": "brand/logo.png", "handle": "@migimnasio", "line": "C/ Toro 12 · Salamanca",
   "bg": "#111111", "fg": "#FFFFFF", "font": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"}
  ```
- Web UI: `new.html` gets an optional `<input type="file" name="logo" accept="image/png">` and text inputs `handle`, `line`. The upload handler in `web/app.py` writes them to `sessions/<name>/brand/`. If absent, the repo-level `brand/` is used; if that is absent too, the brand layer is off (no error).

### Changes

1. **`planner/_common.py:DEFAULT_CONFIG`** – add `"brand": True, "logo_w": 160, "logo_opacity": 0.6, "logo_inset_x": 48, "logo_bottom_frac": 0.177, "end_card": True, "end_card_frames": 45, "end_card_logo_w": 480, "end_card_text_size": 48`.

2. **`edl.py:build_edl`** – new optional arg `brand: dict | None` (loaded by `session/planner.py:run_planner` from `session_dir/brand/brand.json`, else repo `brand/brand.json`, else `None`; paths made relative to session dir or absolute, plus `logo_sha256`). Store as `edl["brand"] = {...} | None`. Pass to `build_clips`.

3. **`planner/pipeline.py:build_clips`** – after building clips, if `brand` and `config["end_card"]`: call `_split_end_card(clips, slots, config)`:
   - Take the close clip `c`. `k = min(config["end_card_frames"], c["n_frames"] - 30)`; if `k < 15` → append warning `end_card_skipped`, return.
   - `c["n_frames"] -= k`; `c["out_s"] = c["in_s"] + c["n_frames"]/30` (close is 1.0x, no ramp); `c["timeline_end_f"] -= k`.
   - Append clip `{"slot": c["slot"] + 1, "role": "end_card", "candidate_id": "end_card", "src": brand["logo"], "src_sha256": brand["logo_sha256"], "type": "image", "src_w"/"src_h": PNG dims (use Pillow, already a dep), "in_s": 0, "out_s": k/30, "n_frames": k, "speed": 1.0, "timeline_start_f": c["timeline_end_f"], "timeline_end_f": c["timeline_end_f"] + k, "layout": "crop", "crop": {0,0,1,1}, "crop_px": full, "subject_cropped": False, "src_fps_nominal": 30, "effect": "end_card", "effect_params": {bg, fg, handle, line, font, logo_w, text_size}, "warnings": []}`.
   - Invariants: P1 compares `clips` to `slots` 1:1 — either append a synthetic slot `{"slot": n, "role": "end_card", "start_f", "end_f"}` to the `slots` list passed into `assert_invariants` (recommended: do the split *before* `assert_invariants` and pass `slots + [end_slot]`), or exempt `end_card` in P1. P2 fine (unique id). P3/P4/P5 skip for `type == "image"` already. P6 holds since we moved frames, not created them. P7 skip (image). P8: full-frame crop must be even → PNG dims may be odd; set `crop_px` to `{0,0,even(w),even(h)}`. P9: `k ≥ 15` violates `n_frames ≥ 30`. **Exempt `role == "end_card"` from P9** (one-line condition) rather than forcing 30 frames: a 1 s card is fine, 1.5 s is the default.
   - Also the `slots.json` is unchanged on disk; only the in-memory slots list for invariants gets the synthetic slot. Document this in 06/07.

4. **`planner/pipeline.py`** – also stamp `clip["effect_params"]["logo"] = {path, w, opacity, inset_x, bottom_frac}` on every non-end-card clip when `brand` and `config["brand"]`. Alternative that avoids touching every clip: read `edl["brand"]` in the render. **Choose the render-reads-`edl["brand"]` option**: `render_segments`/`render_preview_segments` already receive `edl`; pass `edl.get("brand")` down to `render_segment` → `render_video_segment`/`render_image_segment` as `logo: dict | None`. Less EDL noise, one code path.

5. **`render/_common.py`** – add:
   ```
   LOGO_FILTER_TEMPLATE = (
       "movie='{logo}',scale={lw}:-1:flags=lanczos,format=rgba,colorchannelmixer=aa={opacity}[logo];"
       "[v0][logo]overlay=W-w-{inset}:H-h-{bottom}:format=auto"
   )
   ```
   This requires `-filter_complex` form, since `movie=` is a source. Simplest uniform approach: **switch `render_video_segment`'s `crop` branch to `-filter_complex` too** (label the main chain `[0:v]…[v0]`, then the logo branch, `-map "[v]"`). The `blur_pad` branch and image branch get the same tail. Keep the current `-vf` path only when `logo is None` if you want a minimal diff; but two code paths for the same chain is exactly what bites later, so convert all three renderers to `-filter_complex` with a shared `_finish(chain, logo, target)` helper that appends `setsar=1,format=yuv420p` and the optional logo overlay. Scale `lw`, `inset`, `bottom` by `target["w"]/1080`.
   - Apply overlay **after** `color_fix` and hook text, before `setsar/format`.

6. **`render/segments.py` – end card renderer** `render_end_card_segment(clip, brand, out_path, threads, preview)`:
   ```
   ffmpeg -y -f lavfi -i "color=c={bg}:s={tw}x{th}:r=30:d={k/30}" -i {logo}
     -filter_complex "[1:v]scale={elw}:-1:flags=lanczos[lg];
                      [0:v][lg]overlay=(W-w)/2:(H-h)/2-{text_size*1.5}[v1];
                      [v1]drawtext=fontfile='{font}':text='{handle}':fontsize={ts}:fontcolor={fg}:x=(w-text_w)/2:y=H/2+{elh/2}+{gap},
                          drawtext=fontfile='{font}':text='{line}':fontsize={ts*0.7}:fontcolor={fg}@0.8:x=(w-text_w)/2:y=H/2+{elh/2}+{gap}+{ts*1.4},
                          fade=t=in:st=0:d=0.25,setsar=1,format=yuv420p[v]"
     -map "[v]" -fps_mode cfr -frames:v {k} COLOR_ARGS -an codec_args out
   ```
   - Reuse `_drawtext_escape` from Step 1. `elh` = logo height after scaling (compute from PNG aspect via Pillow at planner time and store in `effect_params`, so the render does no probing).
   - `render_segment` dispatches on `clip["effect"] == "end_card"` before the image/video branch.
   - Do **not** put the watermark on the end card.

7. **`render/checks.py`** – R2 runs per clip against `preview_segments`; the end card is rendered at both resolutions so nothing changes. R1/R3/R6 unchanged.

8. **`render/profile.py`** – add `logo_filter_template`, `end_card_filter_template`, and `brand_sha256` (hash of `brand.json` + logo bytes) to the profile.

9. **`session/planner.py:run_planner`** – `_load_brand(session_dir)` (≈15 lines: try session `brand/brand.json`, then repo `brand/brand.json` via `Path(__file__).parents[3] / "brand"`, else `None`; resolve logo path to absolute, compute `logo_sha256`, read PNG dims with Pillow). Pass to `build_edl(brand=…)`.

10. **`web/app.py` + `web/templates/new.html`** – optional logo upload + `handle` + `line` fields → `sessions/<name>/brand/{logo.png,brand.json}`. `web/pipeline.py:STAGE_ARTIFACTS["planner"]` unchanged (`edl.json`). Regenerate-from-planner picks up a new brand file automatically.

11. **`.gitignore`** – add `brand/logo.png` and `brand/brand.json`; commit `brand/README.md` explaining the format.

### Tests
- `tests/test_planner.py`: `test_end_card_splits_close_slot` — close of 60 frames + `end_card_frames=45` → close 30 frames + card 30 frames? No: `k = min(45, 60-30) = 30` → close 30, card 30, `sum(n_frames)` unchanged, invariants pass. Close of 40 → `k = 10 < 15` → skipped + warning. Close of 90 → close 45, card 45.
- `tests/test_render.py`: extend e2e with a generated 200×80 RGBA PNG (Pillow), `edl["brand"]`, and an `end_card` clip; assert R1/R2/R3/R6 pass and `nb_read_frames(reel) == duration_f`. Assert the bottom-right pixel region of frame 0 of a normal segment differs from a render without brand (cheap proof the overlay landed): decode one frame with ffmpeg to PNG, compare crops with Pillow.
- Manual: phone check that the logo is not under the Reels right-hand action column (likes/comments sit at the right edge from ~40% to ~75% height; bottom-right at 17.7% from the bottom is below that column and above the caption).

### Skip for now
- Animated logo, logo on the end card sliding in, brand LUT (idea #10). Static + fade is enough to be recognisable.
- Per-session brand override UI beyond the three fields.

---

## Final pass (after all three)

1. Bump `edl.VERSION` to 5; update the JSON schema in `07-edl-contract.md` (`effect` enum: `none|kenburns|ramp|end_card`; `role` enum + `end_card`; optional top-level `brand`; `speed` now always 1.0).
2. Update `render_profile` templates and confirm `profile_sha256` changes (there is a determinism test in `test_render.py`; re-record its expectations if it pins the hash).
3. Run a real session end to end via the web UI; check R1–R6 all `ok`; watch it on a phone.
4. Record ceilings in code as `# ponytail:` comments: hard-step ramp, no text wrapping, static logo.
