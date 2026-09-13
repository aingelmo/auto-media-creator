# Task Completion Checklist

Before considering a coding task done:
1. `uv run ruff check .` — no lint errors.
2. `uv run ty check` — no type errors.
3. `uv run pytest -q` — all tests pass.
4. If behavior tied to a spec'd invariant/schema changed, confirm the relevant
   file under `docs/architecture/` still matches (update the doc if the
   change is an intentional spec change; otherwise the code is wrong, not the doc).
5. If touching `src/edl_agent/`, follow `AGENTS.md`: English Google-style docstrings,
   ~150-200 LOC/file, one spec-section per file (see `mem:conventions`).
6. If the task changed structure/conventions that a memory describes (module
   layout, lint/type config, docstring rules, etc.), update the relevant
   memory before finishing — memories don't update themselves.
