# Docstrings

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

When done: `uv run ruff check .`, `uv run ty check`, `uv run pytest -q` —
all must pass.
