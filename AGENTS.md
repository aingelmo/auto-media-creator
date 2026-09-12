# AGENTS.md

## Project

`edl-agent`: builds an EDL (edit decision list) for automated video montage —
ingest → candidate selection → planning (LLM-assisted) → render, plus proxy
verification. Full design spec: `docs/architecture/arquitectura_edl_agent_v4.md`
(Spanish; section numbers like `#4.3` referenced throughout the code).

## Setup / commands

- Package manager: `uv` (not pip/poetry). Install: `uv sync`.
- Run: `uv run python scripts/run_e2e.py ...` or `uv run python -m edl_agent...`.
- Checks (all must pass before considering a task done):
  `uv run ruff check .`, `uv run ty check`, `uv run pytest -q`.

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
- Preserve spec references (`#4.3`, `#6.2.3`, etc.) — they point into
  `docs/architecture/arquitectura_edl_agent_v4.md`.

Translate Spanish comments/docstrings to English as you touch a file.
Exception: LLM prompt content in `selector.py` (`SYSTEM_PROMPT`,
`USER_PROMPT_TEMPLATE`, `REINFORCED_SUFFIX`, JSON schema `description`
fields) stays in Spanish — it's sent to the model, not documentation.

Keep lines ≤88 chars (ruff `E501`).

## File size

- Aim for ~150–200 lines of code (excluding docstrings/blanks) per file, one
  responsibility/spec-section each. Verbose docstrings can push total length
  well past that — don't count against the limit.
- Split trigger: file covers more than one spec section, or has more than
  4–5 public functions, not raw line count.
- Exempt: `tests/**`, `scripts/**`, fixtures/data tables.
