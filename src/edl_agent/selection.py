"""Layer 5 - S-checks (#8.1) and rules fallback (#8.6).

Reconciles a `selection.json` (LLM output) against `candidates.json` and
fills, role by role, any gaps with the 0-EUR rules fallback. Produces the
`selected` list consumed by `planner.assign_slots`. If there is no LLM
selection (``selection is None``), the entire result comes from the
fallback.
"""

from __future__ import annotations

ROLES = ("hook", "develop", "close")

FALLBACK_HOOK_MOTION_BG_MAX = 0.4
FALLBACK_HOOK_SHARPNESS_MIN = 0.5


def _centrality(bbox: tuple) -> float:
    cx = (bbox[0] + bbox[2]) / 2
    return 1 - 2 * abs(cx - 0.5)


def _slot_indices(slots: list[dict], role: str) -> list[int]:
    return [s["slot"] for s in slots if s["role"] == role]


def _admits(cand: dict, slot_indices: list[int]) -> bool:
    return any(s in cand["admits_slots"] for s in slot_indices)


# --------------------------------------------------------------------------
# 8.1 S-checks on selection.json
# --------------------------------------------------------------------------


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
            and other fields passed through unchanged).
        candidates_by_id: Mapping `candidate_id -> candidate dict` (see
            `candidates.build_video_candidates`). Used to validate
            candidate ids and to read `kind` (for S4) and `admits_slots`
            (for S5).
        slots: Slot dicts, as in `slots.json["slots"]`.

    Returns:
        `(cleaned, warnings)`:
        - `cleaned`: surviving entries, grouped by role (`ROLES` order)
          and re-ranked 1..N within each role (a new `rank` key is
          assigned/overwritten, ignoring any rank the LLM proposed).
        - `warnings`: one entry per dropped/moved candidate:
          `"s2_dropped:{id}"` (unknown or duplicate candidate_id),
          `"s4_moved:{id}->close"` / `"s4_moved:{id}->develop"` (role
          reassigned to match the candidate's `kind`: hook must be `peak`,
          close must not be `peak`), `"s5_dropped:{id}"` (candidate's
          window doesn't admit any slot of its assigned role).
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
        elif entry["role"] == "close" and kind == "peak":
            entry["role"] = "develop"
            warnings.append(f"s4_moved:{entry['candidate_id']}->develop")

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

    by_role: dict[str, list[dict]] = {role: [] for role in ROLES}
    for entry in cleaned:
        by_role[entry["role"]].append(entry)
    for entries in by_role.values():
        for i, entry in enumerate(entries, start=1):
            entry["rank"] = i

    return [e for role in ROLES for e in by_role[role]], warnings


# --------------------------------------------------------------------------
# 8.6 Rules fallback, per role
# --------------------------------------------------------------------------


def fallback_hook(
    candidates: list[dict], slot_indices: list[int], used_ids: set[str]
) -> tuple[dict | None, list[str]]:
    """Pick a `peak` candidate for the hook role by rules, per #8.6.

    Args:
        candidates: All candidate dicts (from `candidates_json["candidates"]`).
        slot_indices: Slot indices for the hook role (see `_slot_indices`).
        used_ids: Candidate ids already claimed by another role; excluded
            from the pool.

    Returns:
        `(entry, warnings)`:
        - `entry`: a selection entry with `candidate_id`, `role="hook"`,
          `rank=1`, `exercise="unknown"`, `reason="rules_fallback"`; `None`
          if no `peak` candidate in the pool admits an hook slot while
          meeting the motion/sharpness thresholds.
        - `warnings`: `["sharpness_cross_clip"]` (W5) if the pool spans
          more than one source clip, since sharpness is only comparable
          within a clip (#4.2); empty otherwise. Empty (`[]`) whenever
          `entry` is `None`.
    """
    pool = [
        c
        for c in candidates
        if c["kind"] == "peak"
        and c["id"] not in used_ids
        and _admits(c, slot_indices)
        and c["motion_bg"] <= FALLBACK_HOOK_MOTION_BG_MAX
        and c["sharpness"] >= FALLBACK_HOOK_SHARPNESS_MIN
    ]
    if not pool:
        return None, []
    # W5: sharpness is relative to each clip (#4.2); filtering by a global
    # threshold across several `src` values compares non-comparable numbers.
    warnings = ["sharpness_cross_clip"] if len({c["src"] for c in pool}) > 1 else []
    single_subject = [c for c in pool if not c["multi_subject"]]
    pool = single_subject or pool
    best = max(pool, key=lambda c: c["kp_speed"])
    entry = {
        "candidate_id": best["id"],
        "role": "hook",
        "rank": 1,
        "exercise": "unknown",
        "reason": "rules_fallback",
    }
    return entry, warnings


def fallback_close(
    candidates: list[dict], slot_indices: list[int], used_ids: set[str]
) -> tuple[dict | None, list[str]]:
    """Pick a candidate for the close role by rules, per #8.6.

    Prefers `calm`, then `image`, and only falls back to `peak` as a last
    resort (least-action one, flagged with a warning).

    Args:
        candidates: All candidate dicts (from `candidates_json["candidates"]`).
        slot_indices: Slot indices for the close role (see `_slot_indices`).
        used_ids: Candidate ids already claimed by another role; excluded
            from the pool.

    Returns:
        `(entry, warnings)`:
        - `entry`: a selection entry with `candidate_id`, `role="close"`,
          `rank=1`, `exercise="unknown"`, `reason="rules_fallback"`; `None`
          if no `calm`/`image`/`peak` candidate admits a close slot.
        - `warnings`: `["close_not_calm"]` only when a `peak` candidate had
          to be used as the last resort; empty otherwise.
    """
    def admissible(kinds: set[str]) -> list[dict]:
        return [
            c
            for c in candidates
            if c["kind"] in kinds
            and c["id"] not in used_ids
            and _admits(c, slot_indices)
        ]

    calm = admissible({"calm"})
    if calm:
        best = max(calm, key=lambda c: c["sharpness"] * _centrality(c["subject_bbox"]))
        return {
            "candidate_id": best["id"],
            "role": "close",
            "rank": 1,
            "exercise": "unknown",
            "reason": "rules_fallback",
        }, []

    images = admissible({"image"})
    if images:
        best = max(images, key=lambda c: c["score_cv"])
        return {
            "candidate_id": best["id"],
            "role": "close",
            "rank": 1,
            "exercise": "unknown",
            "reason": "rules_fallback",
        }, []

    peaks = admissible({"peak"})
    if peaks:
        best = min(peaks, key=lambda c: c["kp_speed"])
        return {
            "candidate_id": best["id"],
            "role": "close",
            "rank": 1,
            "exercise": "unknown",
            "reason": "rules_fallback",
        }, ["close_not_calm"]

    return None, []


def fallback_develop(
    candidates: list[dict], slot_indices: list[int], used_ids: set[str], k: int
) -> list[dict]:
    """Pick up to `k` candidates for the remaining develop slots by rules, per #8.6.

    Ranks eligible `peak` candidates by `score_cv` and round-robins across
    source clips, so develop shots come from as many different sources as
    the pool allows rather than piling onto one clip.

    Args:
        candidates: All candidate dicts (from `candidates_json["candidates"]`).
        slot_indices: Slot indices for the develop role (see
            `_slot_indices`).
        used_ids: Candidate ids already claimed by another role; excluded
            from the pool.
        k: Maximum number of entries to return.

    Returns:
        Up to `k` selection entries, each with `candidate_id`,
        `role="develop"`, `rank` (1-indexed, in the order chosen),
        `exercise="unknown"`, `reason="rules_fallback"`.
    """
    pool = sorted(
        (
            c
            for c in candidates
            if c["kind"] == "peak"
            and c["id"] not in used_ids
            and _admits(c, slot_indices)
        ),
        key=lambda c: c["score_cv"],
        reverse=True,
    )
    by_src: dict[str, list[dict]] = {}
    for c in pool:
        by_src.setdefault(c["src"], []).append(c)

    ordered: list[dict] = []
    while len(ordered) < k and by_src:
        for src in list(by_src):
            if len(ordered) >= k:
                break
            ordered.append(by_src[src].pop(0))
            if not by_src[src]:
                del by_src[src]

    return [
        {
            "candidate_id": c["id"],
            "role": "develop",
            "rank": i + 1,
            "exercise": "unknown",
            "reason": "rules_fallback",
        }
        for i, c in enumerate(ordered)
    ]


# --------------------------------------------------------------------------
# 8.5 Orchestration: S-checks + fallback -> `selected` for the planner
# --------------------------------------------------------------------------


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
