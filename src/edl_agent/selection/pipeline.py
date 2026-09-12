"""8.5 Orchestration: S-checks + fallback -> `selected` for the planner."""

from __future__ import annotations

from ._common import _slot_indices
from .fallback import fallback_close, fallback_develop, fallback_hook
from .s_checks import apply_s_checks


def _preempt_develop(
    cleaned: list[dict], candidate_id: str, warnings: list[str], role: str
) -> list[dict]:
    """Reclaim for `role` (hook/close) a candidate already assigned to develop.

    Develop has more slack (N slots, typically more candidates) than
    hook/close (mandatory, 1 slot each). The gap this leaves is later
    refilled with `fallback_develop` over the remaining pool.

    Args:
        cleaned: Current selection entries.
        candidate_id: Candidate id to reclaim from the develop role.
        warnings: Warnings list, mutated in place with
            `"{role}_preempted_develop:{candidate_id}"`.
        role: Role reclaiming the candidate (`"hook"` or `"close"`).

    Returns:
        `cleaned` with the matching develop entry removed.
    """
    warnings.append(f"{role}_preempted_develop:{candidate_id}")
    return [
        e
        for e in cleaned
        if not (e["role"] == "develop" and e["candidate_id"] == candidate_id)
    ]


def build_selected(
    candidates_json: dict,
    slots_json: dict,
    selection: dict | None,
) -> tuple[list[dict], list[str], list[str]]:
    """Reconcile `selection` against candidates/slots and fill gaps by rules, per #8.5.

    Args:
        candidates_json: Parsed `candidates.json`, with a `candidates` key
            (list of candidate dicts).
        slots_json: Parsed `slots.json`, with a `slots` key (list of slot
            dicts).
        selection: Parsed LLM selection output (see
            `selector.selection_schema`), or `None` to skip S-checks
            entirely and let every role come from the rules fallback.

    Returns:
        `(selected, warnings, fallback_roles)`:
        - `selected`: final list of selection entries (LLM-derived plus any
          fallback ones) ready for `planner.assign_slots`.
        - `warnings`: all warnings accumulated from S-checks and the
          fallback (see `apply_s_checks`, `fallback_hook`, `fallback_close`,
          `_preempt_develop`).
        - `fallback_roles`: which of `"hook"`, `"close"`, `"develop"` needed
          the rules fallback for at least one slot.
    """
    candidates = candidates_json["candidates"]
    candidates_by_id = {c["id"]: c for c in candidates}
    slots = slots_json["slots"]
    develop_k = sum(1 for s in slots if s["role"] == "develop")

    if selection is not None:
        cleaned, warnings = apply_s_checks(selection, candidates_by_id, slots)
    else:
        cleaned, warnings = [], []

    fallback_roles: list[str] = []
    used_ids = {e["candidate_id"] for e in cleaned}

    if not any(e["role"] == "hook" for e in cleaned):
        entry, hook_warnings = fallback_hook(
            candidates, _slot_indices(slots, "hook"), used_ids
        )
        if entry is None:
            # #6.2.5: nothing free admits hook; reclaim whatever develop
            # has that's admissible.
            develop_ids = {e["candidate_id"] for e in cleaned if e["role"] == "develop"}
            entry, hook_warnings = fallback_hook(
                candidates, _slot_indices(slots, "hook"), used_ids - develop_ids
            )
            if entry:
                cleaned = _preempt_develop(
                    cleaned, entry["candidate_id"], warnings, "hook"
                )
        warnings.extend(hook_warnings)
        if entry:
            cleaned.append(entry)
            used_ids.add(entry["candidate_id"])
            fallback_roles.append("hook")

    if not any(e["role"] == "close" for e in cleaned):
        entry, close_warnings = fallback_close(
            candidates, _slot_indices(slots, "close"), used_ids
        )
        if entry is None:
            develop_ids = {e["candidate_id"] for e in cleaned if e["role"] == "develop"}
            entry, close_warnings = fallback_close(
                candidates, _slot_indices(slots, "close"), used_ids - develop_ids
            )
            if entry:
                cleaned = _preempt_develop(
                    cleaned, entry["candidate_id"], warnings, "close"
                )
        warnings.extend(close_warnings)
        if entry:
            cleaned.append(entry)
            used_ids.add(entry["candidate_id"])
            fallback_roles.append("close")

    develop_count = sum(1 for e in cleaned if e["role"] == "develop")
    if develop_k > 0 and develop_count < develop_k:
        extra = fallback_develop(
            candidates,
            _slot_indices(slots, "develop"),
            used_ids,
            develop_k - develop_count,
        )
        for i, entry in enumerate(extra):
            entry["rank"] = develop_count + i + 1
        cleaned.extend(extra)
        used_ids.update(e["candidate_id"] for e in extra)
        if "develop" not in fallback_roles:
            fallback_roles.append("develop")

    return cleaned, warnings, fallback_roles
