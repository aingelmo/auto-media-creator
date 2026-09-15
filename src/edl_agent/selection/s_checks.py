"""8.1 S-checks on selection.json."""

from __future__ import annotations

from edl_agent.selection._common import ROLES, _admits, _slot_indices

HOOK_LINE_MAX_WORDS = 8


def clean_hook_line(raw: object) -> str:
    """Trim/unquote the LLM's `hook_line`; `""` if missing or over 8 words."""
    line = str(raw or "").strip().strip("\"'“”«»").strip()
    if not 0 < len(line.split()) <= HOOK_LINE_MAX_WORDS:
        return ""
    return line[:40]


def apply_s_checks(
    selection: dict,
    candidates_by_id: dict,
    slots: list[dict],
) -> tuple[list[dict], list[str]]:
    """Apply checks S2-S5 to `selection`, per #8.1.

    S1 (incomplete status) is resolved outside this function (it's the
    caller of the LLM's concern); any per-role gaps left by S5 are covered
    by the fallback in `build_selected`.

    Args:
        selection: Parsed LLM selection output (see
            `selector.selection_schema`). Reads `selected` (list of dicts,
            each with `candidate_id` (str), `role` (str), `exercise` (str),
            and other fields passed through unchanged) and `hook_line`
            (str, optional).
        candidates_by_id: Mapping `candidate_id -> candidate dict` (see
            `candidates.build_video_candidates`). Used to validate
            candidate ids and to read `kind` (for S4) and `admits_slots`
            (for S5).
        slots: Slot dicts, as in `slots.json["slots"]`.

    Returns:
        `(cleaned, warnings)`:
        - `cleaned`: surviving entries, grouped by role (`ROLES` order)
          and re-ranked 1..N within each role (a new `rank` key is
          assigned/overwritten, ignoring any rank the LLM proposed). The
          hook entry also carries `hook_line` (see `clean_hook_line`; `""`
          when absent/invalid) so it flows to the planner untouched.
        - `warnings`: one entry per dropped/moved candidate:
          `"s2_dropped:{id}"` (unknown or duplicate candidate_id),
          `"s4_moved:{id}->close"` (role reassigned because a non-`peak`
          candidate was picked for hook, which must be `peak`), or
          `"s5_dropped:{id}"` (candidate's window doesn't admit any slot
          of its assigned role), plus `"hook_line_invalid"` when a
          non-empty `hook_line` was rejected (empty/too long). `close` may
          be `peak`-kind: the prompt already tells the model to prefer
          calm/image there and only use a still-looking peak as a last
          resort, so its own rank ordering
          is trusted instead of a hard kind filter.
    """
    warnings: list[str] = []
    seen: set[str] = set()
    cleaned: list[dict] = []

    for entry in selection.get("selected", []):
        cid = entry.get("candidate_id")
        if cid not in candidates_by_id or cid in seen:
            warnings.append(f"s2_dropped:{cid}")
            continue
        seen.add(cid)
        cleaned.append(dict(entry))

    for entry in cleaned:
        kind = candidates_by_id[entry["candidate_id"]]["kind"]
        if entry["role"] == "hook" and kind != "peak":
            entry["role"] = "close"
            warnings.append(f"s4_moved:{entry['candidate_id']}->close")

    # S5: the LLM doesn't know `admits_slots` (it isn't sent to it); here we
    # drop whatever it chose for a role whose slot(s) don't fit its window,
    # so `build_selected`'s fallback can cover that gap.
    admissible: list[dict] = []
    for entry in cleaned:
        cand = candidates_by_id[entry["candidate_id"]]
        if not _admits(cand, _slot_indices(slots, entry["role"])):
            warnings.append(f"s5_dropped:{entry['candidate_id']}")
            continue
        admissible.append(entry)
    cleaned = admissible

    hook_line = clean_hook_line(selection.get("hook_line"))
    if selection.get("hook_line") and not hook_line:
        warnings.append("hook_line_invalid")

    by_role: dict[str, list[dict]] = {role: [] for role in ROLES}
    for entry in cleaned:
        by_role[entry["role"]].append(entry)
    for entries in by_role.values():
        for i, entry in enumerate(entries, start=1):
            entry["rank"] = i
    for entry in by_role["hook"]:
        entry["hook_line"] = hook_line

    return [e for role in ROLES for e in by_role[role]], warnings
