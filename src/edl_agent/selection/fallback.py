"""8.6 Rules fallback, per role."""

from __future__ import annotations

from ._common import (
    FALLBACK_HOOK_MOTION_BG_MAX,
    FALLBACK_HOOK_SHARPNESS_MIN,
    _admits,
    _centrality,
)


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
