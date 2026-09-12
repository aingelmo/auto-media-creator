# Conventions

- `from __future__ import annotations` at the top of every module.
- `src/edl_agent/` is AI-only (see `AGENTS.md`): docstrings optimized for AI
  comprehension over brevity, full Google-style (Args/Returns/Raises) in
  English on every public function/method, documenting dict-shaped params
  (`clip`, `slot`, `config`, `candidate`, ...) since they have no static
  typing. Comments/docstrings are being translated from Spanish to English
  as files are touched; exception: LLM prompt strings in `selector/prompts.py`
  stay in Spanish (sent to the model, not documentation).
- Docstrings/comments cross-reference `docs/architecture/arquitectura_edl_agent_v4.md`
  by section number, e.g. `"""#6 Planner determinista..."""` or
  `"Ver docs/architecture/... #4.1."`. When adding code implementing a spec'd
  behavior, add the matching `#<section>` reference.
- File size: aim for ~150-200 LOC per file (excluding docstrings/blanks), one
  responsibility/spec-section each; split trigger is >1 spec section or
  >4-5 public functions, not raw line count. `tests/**`/`scripts/**` exempt.
  Each former single-file module (`ingest.py`, `features.py`, `candidates.py`,
  `selector.py`, `planner.py`, `session.py`, `render.py`, `selection` logic
  formerly in `verify.py`) is now a package (`edl_agent/<name>/`) with a
  `_common.py` for shared helpers; imports across `edl_agent` are absolute
  (`from edl_agent.planner._common import ...`), not relative.
- Session artifacts (manifest.json, candidates.json, selection.json, edl.json) are
  plain dicts written via `json.dump(..., indent=2, ensure_ascii=False)` — no
  dataclass/pydantic schema layer; the architecture doc's tables ARE the schema.
- Planner invariants (P1-P9, §8.2) are enforced with asserts that raise `PlannerError`
  on failure — deliberately never auto-repaired (a failure is a session bug, not a
  correctable condition). Contrast with selection S-checks (§8.1) and warnings W1-W5
  (§8.3), which the code IS expected to repair/tolerate.
- Tests favor property-style tests over synthetic candidates (see
  `tests/test_planner.py` building slots/sources with multiple aspect ratios) rather
  than fixture-heavy unit tests.

See `mem:core` for the package map, `mem:tech_stack` for lint/type-check config.
