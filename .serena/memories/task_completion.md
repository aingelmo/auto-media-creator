# Task Completion Checklist

Before considering a coding task done:
1. `uv run pytest` — all tests pass.
2. `uv run ruff check .` — no lint errors.
3. If behavior tied to a spec'd invariant/schema changed, confirm
   `docs/architecture/arquitectura_edl_agent_v4.md` still matches (update the doc if the
   change is an intentional spec change; otherwise the code is wrong, not the doc).
