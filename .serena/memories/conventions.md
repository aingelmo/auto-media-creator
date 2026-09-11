# Conventions

- `from __future__ import annotations` at the top of every module.
- Docstrings/comments are in Spanish and cross-reference
  `docs/architecture/arquitectura_edl_agent_v4.md` by section number, e.g.
  `"""#6 Planner determinista..."""` or `"Ver docs/architecture/... #4.1."`. When adding
  code implementing a spec'd behavior, add the matching `#<section>` reference.
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
