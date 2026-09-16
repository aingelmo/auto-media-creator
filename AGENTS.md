# AGENTS.md

## Project

`edl-agent`: builds an EDL (edit decision list) for automated video montage —
ingest → candidate selection → planning (LLM-assisted) → render, plus proxy
verification. Full design spec: `docs/architecture/README.md` and its linked
section files (Spanish; section numbers like `#4.3` referenced throughout the
code map 1:1 to file prefixes, e.g. `#4.3` → `docs/architecture/04-features.md`).

## Setup / commands

- Package manager: `uv` (not pip/poetry). Install: `uv sync`.
- Run: `uv run python scripts/run_e2e.py ...` or `uv run python -m edl_agent...`.
- Web UI: `uv run scripts/run_web.py [--host HOST] [--port PORT]` (defaults
  to `127.0.0.1:8000`); open the printed URL in a browser to upload media
  and run sessions without the CLI. This needs no node/npm — it serves the
  React/TS SPA already built into `src/edl_agent/web/static/` (committed to
  git). `src/edl_agent/web/app.py` is a thin JSON API (`/api/*`) over
  `src/edl_agent/web/pipeline.py`, which holds all the pipeline-orchestration
  logic and stays framework-agnostic.
- Frontend dev: only needed when editing the UI itself. `cd frontend && npm
  install`, then `npm run dev` (Vite, hot reload, proxies `/api` and
  `/sessions/*/files` to `:8000` — run the Python server alongside it) or
  `npm run build` to refresh the committed `web/static/` output before
  committing a UI change.
- Checks (all must pass before considering a task done):
  `uv run ruff check .`, `uv run ty check`, `uv run pytest -q`, and for
  frontend changes, `cd frontend && npm run lint && npm run format:check &&
  npx tsc -b --noEmit && npm run build`. If your shell auto-rewrites
  `npm run lint` via an `rtk` hook, see the note in `frontend/README.md` —
  it assumes ESLint and breaks on this project's oxlint setup; use
  `npx oxlint`/`npx oxfmt --check src` directly instead.

## Structure

- `src/edl_agent/` — library code, one subpackage per pipeline stage:
  `ingest/`, `features/`, `candidates/`, `selection/`, `selector/`,
  `planner/`, `render/`, `session/`, plus top-level `edl.py`, `slots.py`,
  `verify.py`, `ollama_client.py`.
- `scripts/` — CLI entry points (e.g. `run_e2e.py`).
- `tests/` — mirrors `src/edl_agent/` layout, one `test_*.py` per module.
- `docs/architecture/` — spec documents referenced by docstrings/comments.

## Docstrings

`src/edl_agent/` is AI-only — no humans read it — so optimize docstrings for
AI comprehension, not brevity. `tests/**` and `scripts/**` are exempt (see
`pyproject.toml`).

Every public function/method gets a full Google-style docstring, in English:

- One-line summary.
- `Args:` — for any `dict`/`list[dict]` parameter (e.g. `clip`, `slot`,
  `config`, `candidate`), document the expected keys and their
  meaning/units, not just "a dict of X". These shapes have no static
  typing, so the docstring is the only spec.
- `Returns:` — describe the shape/meaning if not `None`, documenting dict
  keys where relevant.
- `Raises:` — note domain exceptions (`PlannerError`, `RenderError`,
  `IngestError`, etc.) and when they're raised.
- Preserve spec references (`#4.3`, `#6.2.3`, etc.) — they point into the
  section files under `docs/architecture/` (see `docs/architecture/README.md`
  for the number → file mapping).

Translate Spanish comments/docstrings to English as you touch a file.
Exception: LLM prompt content in `selector.py` (`SYSTEM_PROMPT`,
`USER_PROMPT_TEMPLATE`, `REINFORCED_SUFFIX`, JSON schema `description`
fields) stays in Spanish — it's sent to the model, not documentation.

Keep lines ≤88 chars (ruff `E501`).

## Commits

- One logical change per commit. If a session touches unrelated concerns
  (e.g. a new feature + an unrelated bug fix + a lint cleanup), split them
  into separate commits — even if all the edits happened together. Check
  `git status`/`git diff` before staging and stage per-concern, not
  everything at once.
- Subject line: Conventional Commits format, `type(scope): description` —
  e.g. `feat(web): add SPA frontend`, `fix(planner): reject overlapping
  slots`, `refactor(render): extract punch-in helper`. `type` is one of
  `feat`, `fix`, `refactor`, `build`, `docs`, `test`, `chore`. `scope` is the
  touched subpackage/area (e.g. `web`, `planner`, `render`, `ingest`) or
  omitted if repo-wide. Description: imperative present tense, ≤72 chars
  total, no trailing period.
- Body: explain *why*, not what (the diff already shows what) — root cause
  for bug fixes, motivation/constraint for features or refactors. Skip the
  body only for purely mechanical changes (lint/format-only, typo fixes).
- AI-authored commits end with the `Co-Authored-By:` trailer per the
  session's attribution instructions.

## File size

- Aim for ~150–200 lines of code (excluding docstrings/blanks) per file, one
  responsibility/spec-section each. Verbose docstrings can push total length
  well past that — don't count against the limit.
- Split trigger: file covers more than one spec section, or has more than
  4–5 public functions, not raw line count.
- Exempt: `tests/**`, `scripts/**`, fixtures/data tables.
