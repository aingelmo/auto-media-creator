# Suggested Commands

- Run tests: `uv run pytest`
- Run a single test file/case: `uv run pytest tests/test_planner.py -k <name>`
- Lint: `uv run ruff check .`
- Type-check: `uv run ty check`
- Run the manual e2e driver over a session dir: `uv run python scripts/run_e2e.py <session_dir>`
  (see its `main()` for expected args; adds `src/` to `sys.path` itself).
- Local LLM selector testing (avoid Gemini API cost): pass `client=OllamaClient()`
  (`ollama_client.py`) into `session.run_selection` instead of the default
  `google.genai.Client()`.
- No non-standard Linux shell command forms noted — standard `git`/`ls`/`grep` apply.
