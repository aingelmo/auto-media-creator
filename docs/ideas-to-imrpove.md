# Ideas to take the gym reels to the next level

## Context

The pipeline (ingest → CV features → LLM selector → beat-snapped planner → ffmpeg render) is stable. The output today is: hard cuts on beats, 9:16 crop/blur-pad, per-clip colour match, loudnormed music, optional 0.5x hook. Nothing on top of the footage: no text, no logo, no speed ramps, no diegetic sound, no transitions. Competing gym accounts differentiate on exactly those layers, not on cut accuracy.

Ranked by (impact on "stands out") / (effort given the current code). Everything below needs only ffmpeg filters already in use and the existing EDL/planner, no new dependencies.

## Tier 1 — do these first

1. **Hook text overlay (first 1–2 s).** Biggest retention driver on Reels. The selector already writes reasoning per pick; add one field to `selection.json` (`hook_line`, 3–6 words, e.g. "Nadie levanta así en Salamanca") and render it with `drawtext` on the hook segment (fade in/out over ~15 frames). Planner copies it into `clip.effect_params`; render adds one filter before `setsar`. Font as a config path.
   - Files: `selector/prompts.py`, `selector/_common.py` (schema), `planner`, `render` segment filter, `edl.py` contract.
2. **Brand layer.** Small logo watermark (`overlay` of a PNG, bottom-right, ~60% opacity) on every segment plus a 1–2 s end card (logo + handle + address) replacing or following the close slot. One `movie=`/`overlay` filter and one image segment reusing §10.3. Makes every reel recognisable as *your* gym in the feed before the caption is read.
3. **Speed ramp on the peak.** You already know `t_peak` and have 60 fps sources. Instead of flat 0.5x, ramp: 0.4x for ~10 frames around the peak, snap back to 1x. `setpts` with an `if()` expression on `T`; frame count stays exact with `-frames:v`. This is the single most "professional-looking" change and is fully deterministic.
   - Files: planner `in/out` calc (§6.3 needs the source span consumed by a variable-speed segment), render `setpts` template, R2 phash check still works because preview uses the same filter.

## Tier 2 — once tier 1 is in

4. **Beat-synced punch-ins / flash.** On each develop cut: a 4–6 frame 1.0→1.06 zoom (`zoompan`, same 3x pre-scale trick as Ken Burns) or a 2-frame white flash on the hook beat. Stays inside segments, so concat-copy keeps working. Skip `xfade`: it needs re-encoding at joins and breaks the per-segment design.
5. **Diegetic sound under the music.** Plates clanking, breath, a shout at the peak. Extract the original clip audio at ingest (proxies drop it today), keep only the hook and peak segments' audio, duck it to −18 dB under the music with `sidechaincompress` or a fixed `volume`. Needs: ingest audio extraction, EDL `audio.sfx[]`, second `amix` in the final pass. Medium effort, high "feel" payoff.
6. **Exercise / stat captions.** Selector already labels `exercise`. Show "Sentadilla · 120 kg" lower-third for 1 s on each develop cut. Same `drawtext` path as #1; weight comes from the trainer via the web UI upload form (optional per clip).
7. **Two variants per session.** Render A/B with different hook clip + hook line (planner is deterministic, so just re-run with `peak_beat_index` / seed varied). Post both, keep the winner. Almost free since segments are cached per clip.

## Tier 3 — strategic, not code-first

8. **Close the evaluation loop.** §13 already says "evaluation is anecdotal". Pull Instagram insights (3 s retention, saves, shares) per reel into `sessions/<name>/metrics.json`, and feed the top-performing hook lines / exercise orderings back into the selector prompt as few-shot examples. This is what actually beats other gyms over months.
9. **Member spotlight reels.** Multi-person tracking exists; add a "follow this member" mode that filters candidates to one track id. Tagged members reshare, which is free distribution.
10. **Brand LUT.** A `lut3d` grade preset per gym (warm, slightly lifted blacks) applied after `color_fix`. Consistency across weeks makes the feed look designed.

## Recommendation

Start with 1 + 2 + 3 in one pass: hook text, logo/end card, speed ramp. Together they change the perceived production level from "auto montage" to "edited", touch only prompt/planner/render, and keep R1–R6 checks intact.

## Verification (for whichever gets picked)

- `uv run pytest -q`, `ruff`, `ty` green.
- Run one real session through the web UI; R1/R2/R6 pass (frame counts exact, preview↔final phash match, monotonic DTS).
- Eyeball on a phone: text legible at 1080x1920, logo not clipped by the Reels UI safe area (keep ≥ 220 px from bottom, ≥ 120 px from top).
