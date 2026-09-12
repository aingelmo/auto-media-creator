# EDL Agent — Core

Automated vertical (9:16) video montage pipeline: ingests raw clips/photos + a music
track, selects highlight moments (via LLM), and deterministically plans/renders a
reel.mp4 synced to the beat.

Single source of truth for the whole design: `docs/architecture/arquitectura_edl_agent_v4.md`
(Spanish, ~974 lines, numbered sections §0-§14). Code comments reference it by section
number (e.g. "#4.2-#4.3", "ver #1, #4"). **Always check this doc before changing
pipeline behavior** — it defines schemas, invariants and fallback rules that the code
must match exactly; the doc is the spec, the code is the implementation.

`AGENTS.md` (repo root) is the second source of truth: it governs docstring style
(AI-oriented, English, Google-style) and per-file size/splitting rules for
`src/edl_agent/`.

## Pipeline (capas/layers), each its own package under `src/edl_agent/`
1. Ingesta (`ingest/`) — probe/normalize sources, build proxies, verify proxy↔original.
2. Features locales (`features/`, `slots.py`) — audio→beat slots, video→per-frame series.
3. Candidatos (`candidates/`) — build selectable candidate windows/images from features.
4. Selector LLM (`selector/`, `ollama_client.py`) — Gemini (`google-genai`) by default,
   or local Ollama for dev, picks candidates per slot role (hook/develop/close).
5. Planner determinista (`planner/`) — assigns candidates to slots, computes in/out,
   crop, effects; asserts invariants P1-P9 (§8.2) — failure is a session error, never
   auto-repaired.
6. Validación (`selection/`, `verify.py`) — S-checks on selection.json (§8.1), W-warnings (§8.3).
7. Preview/Render (`render/`) — ffmpeg segments + concat + two-pass loudnorm.

Each package follows the same shape: a `_common.py` for shared internals plus one
module per sub-concern (e.g. `planner/assignment.py`, `planner/invariants.py`,
`planner/crop.py`, `planner/effects.py`, `planner/timing.py`, `planner/pipeline.py`
as the entrypoint) and an `__init__.py` re-exporting the public API.

Orchestration entrypoints for a whole session live in `session/`:
`run_ingest` → `run_candidates` → `run_selection` → `run_planner`. `edl.py` builds the
final `edl.json` contract (§7).

Each session is a directory under `sessions/<session_id>/` containing
`manifest.json`, `proxies/`, `features/`, `peaks/`, `candidates.json`, `selection.json`,
`edl.json`. `scripts/run_e2e.py` is an ad-hoc manual driver over a session dir, not part
of the library.

See `mem:tech_stack`, `mem:suggested_commands`, `mem:conventions`, `mem:task_completion`.
