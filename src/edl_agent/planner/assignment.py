"""6.2 Assignment: pick one candidate per slot (hook/develop/close).

6.2.5 Relaxation, stages 1-2 (allow repeated exercise, then also allow a
repeated source with a wider anti-overlap gap) are implemented in this
module's `select_develop`. Stages 3-5 (reclaiming a candidate from another
role, pulling in a candidate outside `selected`, filling with images) are
not: `selection.build_selected` covers the reverse direction instead --
if hook/close have no admissible free candidate, one already assigned to
develop is preempted (reclaimed) -- develop is more flexible (N slots,
typically more candidates) -- and the resulting gap is refilled from the
remaining fallback pool. If develop itself still falls short after its own
relaxation stages, this module raises PlannerError.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from edl_agent.planner._common import DEFAULT_CONFIG, PlannerError, admits
from edl_agent.planner.timing import compute_in_out


def _norm_exercise(exercise: str) -> str:
    return exercise.lower().strip()


def _select_single(
    selected: list[dict],
    role: str,
    kinds: set[str] | None,
    candidates_by_id: dict,
    d_f: int,
    speed: float,
) -> dict | None:
    pool = sorted(
        (
            s
            for s in selected
            if s["role"] == role
            and (kinds is None or candidates_by_id[s["candidate_id"]]["kind"] in kinds)
        ),
        key=lambda s: s["rank"],
    )
    for s in pool:
        cand = candidates_by_id[s["candidate_id"]]
        if admits(tuple(cand["window"]), d_f, speed):
            return s
    return None


def _overlaps_used(
    cand: dict, in_s: float, out_s: float, used: list[dict], gap_s: float
) -> bool:
    for u in used:
        if u["src"] != cand["src"]:
            continue
        if in_s < u["out_s"] + gap_s and u["in_s"] < out_s + gap_s:
            return True
    return False


def _take_develop_pool(
    pool: list[dict],
    candidates_by_id: dict,
    free_durations: list[int],
    used: list[dict],
    config: dict,
    k: int,
    *,
    allow_exercise_repeat: bool,
    allow_src_repeat: bool,
    gap_s: float,
) -> list[dict]:
    """One greedy pass over `pool`, honoring the given relaxation level.

    Same admission rules as `select_develop`'s docstring, except the
    exercise/source distinctness checks are skipped per
    `allow_exercise_repeat`/`allow_src_repeat`, and the anti-overlap
    margin used against `used` is `gap_s` instead of
    `config["adjacency_gap_s"]`.
    """
    free_durations = list(free_durations)
    used = list(used)
    taken: list[dict] = []
    prev_exercise: str | None = None
    prev_src: str | None = None
    for s in pool:
        if len(taken) >= k:
            break
        cand = candidates_by_id[s["candidate_id"]]
        admissible_d_f = next(
            (d for d in free_durations if admits(tuple(cand["window"]), d, 1.0)), None
        )
        if admissible_d_f is None:
            continue
        exercise = _norm_exercise(s["exercise"])
        # "unknown" (rules-fallback, #8.6) and "other" (selector's own
        # catch-all, selector/prompts.py) both mean "no real exercise
        # label"; treating repeats of either as a clash would collapse
        # the unlabeled pool down to a single entry.
        if (
            not allow_exercise_repeat
            and prev_exercise is not None
            and exercise == prev_exercise
            and exercise not in ("unknown", "other")
        ):
            continue
        if not allow_src_repeat and prev_src is not None and cand["src"] == prev_src:
            continue
        timing = compute_in_out(
            cand,
            {"start_f": 0, "end_f": admissible_d_f, "beats_rel_f": [0]},
            role="develop",
            speed=1.0,
            config=config,
        )
        if _overlaps_used(cand, timing["in_s"], timing["out_s"], used, gap_s):
            continue
        taken.append(s)
        used.append(
            {"src": cand["src"], "in_s": timing["in_s"], "out_s": timing["out_s"]}
        )
        free_durations.remove(admissible_d_f)
        prev_exercise = exercise
        prev_src = cand["src"]
    return taken


def select_develop(
    selected: list[dict],
    candidates_by_id: dict,
    develop_slots: list[dict],
    used: list[dict],
    config: dict,
) -> list[dict]:
    """Pick the `selected` entries taken for develop slots, per #6.2.3+#6.2.5.

    Walks the develop-role pool in rank order (r1 = best) and greedily
    takes entries that fit a remaining develop slot duration, don't repeat
    the exercise or source of the previously taken entry, and don't
    time-overlap anything already placed on the timeline (respecting
    `config["adjacency_gap_s"]`).

    If that strict pass doesn't fill all `k` slots, retries with the
    first two relaxation stages of #6.2.5 (in order, keeping whichever
    pass took the most entries): allow repeated exercises, then also
    allow a repeated source between adjacent develops (with the
    anti-overlap margin raised to at least 1s, since a same-source cut
    needs more separation to not read as a jump cut). Relaxation stages
    3-5 (reclaiming candidates from other roles, pulling in unused
    candidates outside `selected`, filling with images) are out of this
    function's scope — see the module docstring.

    The final temporal order of the taken entries is decided separately
    by `place_develop_arc` (#6.2.4).

    Args:
        selected: Candidate selections (LLM output reconciled with
            fallback, see `selection.build_selected`). Each entry has
            `candidate_id` (str), `role` (str), `rank` (int, 1 = best),
            `exercise` (str).
        candidates_by_id: Mapping `candidate_id -> candidate dict` (see
            `candidates.build_video_candidates` for the candidate shape).
        develop_slots: Slot dicts with `role == "develop"`, each with
            `start_f`/`end_f` (int, frame bounds).
        used: Timeline segments already claimed by other roles (hook so
            far), each a dict with `src` (str), `in_s`/`out_s` (float,
            seconds). Not mutated in place; each relaxation pass starts
            fresh from this list.
        config: Planner config (see `DEFAULT_CONFIG`); reads
            `adjacency_gap_s` and whatever `compute_in_out` needs.

    Returns:
        Subset of `selected` (role `"develop"`) taken, in rank order —
        not yet placed into slot order (see `place_develop_arc` for that).
    """
    k = len(develop_slots)
    free_durations = [s["end_f"] - s["start_f"] for s in develop_slots]
    pool = sorted(
        (s for s in selected if s["role"] == "develop"),
        key=lambda s: s["rank"],
    )
    default_gap_s = config["adjacency_gap_s"]
    relaxed_gap_s = max(default_gap_s, 1.0)  # #6.2.5 stage 2: same-src needs more room
    # (allow_exercise_repeat, allow_src_repeat, gap_s), in #6.2.5 order.
    levels: list[tuple[bool, bool, float]] = [
        (False, False, default_gap_s),
        (True, False, default_gap_s),  # #6.2.5 stage 1
        (True, True, relaxed_gap_s),  # #6.2.5 stage 2
    ]
    taken: list[dict] = []
    for allow_exercise_repeat, allow_src_repeat, gap_s in levels:
        candidate_taken = _take_develop_pool(
            pool,
            candidates_by_id,
            free_durations,
            used,
            config,
            k,
            allow_exercise_repeat=allow_exercise_repeat,
            allow_src_repeat=allow_src_repeat,
            gap_s=gap_s,
        )
        if len(candidate_taken) > len(taken):
            taken = candidate_taken
        if len(taken) >= k:
            break
    return taken


def arc_order(k: int) -> list[int]:
    """Compute the develop rank-to-slot order, per #6.2.4.

    Builds a "narrative arc" order (rising action then falling) rather than
    strict rank order, so the best-ranked develop shots land roughly in the
    middle of the develop block.

    Args:
        k: Number of develop slots.

    Returns:
        For each develop slot s1..sk (0-indexed in the returned list), the
        1-indexed rank of the candidate to place there. E.g. for `k=4`:
        `[2, 4, 3, 1]`.
    """
    evens = list(range(2, k + 1, 2))
    odds = list(range(1, k + 1, 2))
    return evens + odds[::-1]


def _adjacency_violations(
    chain: list[dict | None], candidates_by_id: dict
) -> list[int]:
    """List indices i where `chain[i]` and `chain[i+1]` repeat exercise or source."""
    bad = []
    for i in range(len(chain) - 1):
        a, b = chain[i], chain[i + 1]
        if a is None or b is None:
            continue
        ca, cb = (
            candidates_by_id[a["candidate_id"]],
            candidates_by_id[b["candidate_id"]],
        )
        if (
            _norm_exercise(a["exercise"]) == _norm_exercise(b["exercise"])
            or ca["src"] == cb["src"]
        ):
            bad.append(i)
    return bad


def place_develop_arc(
    taken: list[dict],
    hook: dict | None,
    close: dict | None,
    candidates_by_id: dict,
) -> tuple[list[dict], bool]:
    """Place the `taken` develop entries into slot order, per #6.2.4.

    Starts from `arc_order(k)`, then repairs up to 3 times by swapping
    adjacent develop entries whenever two neighbors (including the hook
    before and the close after) repeat an exercise or source. If a
    violation can't be fixed by swapping develops (e.g. it's against hook
    or close), falls back to plain rank order.

    Args:
        taken: Develop entries selected by `select_develop`, already
            sorted by rank (rank 1 = best, at index 0).
        hook: The entry placed in the hook slot (or `None`), used only to
            check adjacency against the first develop slot.
        close: The entry placed in the close slot (or `None`), used only to
            check adjacency against the last develop slot.
        candidates_by_id: Mapping `candidate_id -> candidate dict`.

    Returns:
        `(placement, arc_fallback)`: `placement` is `taken` reordered for
        slots s1..sk; `arc_fallback` is `True` if no arc arrangement was
        found and `placement` is just `taken` in rank order (caller should
        add an `"arc_fallback"` warning in that case).
    """
    k = len(taken)
    if k == 0:
        return [], False
    by_rank = {
        i + 1: s for i, s in enumerate(taken)
    }  # taken is already sorted by rank
    order = arc_order(k)
    placement = [by_rank[r] for r in order]

    for _ in range(3):
        chain = [hook, *placement, close]
        violations = _adjacency_violations(chain, candidates_by_id)
        if not violations:
            return placement, False
        i = violations[0]
        # Every violation index touches a develop entry (chain is
        # hook, dev0..dev{k-1}, close), so map it to the develop-side
        # neighbor to swap with: the hook boundary (i == 0) swaps the
        # first develop with the second, the close boundary
        # (i == len(chain) - 2) swaps the last develop with the
        # second-to-last, and internal violations swap the two
        # develops directly.
        if i == 0:
            dev_i = 0
        elif i == len(chain) - 2:
            dev_i = len(placement) - 2
        else:
            dev_i = i - 1
        if dev_i >= 0 and dev_i + 1 < len(placement):
            placement[dev_i], placement[dev_i + 1] = (
                placement[dev_i + 1],
                placement[dev_i],
            )
        else:
            # only one develop slot: no develop-side neighbor to swap with
            break

    chain = [hook, *placement, close]
    if _adjacency_violations(chain, candidates_by_id):
        return list(taken), True  # #6.2.4: rank order, warning: arc_fallback
    return placement, False


@dataclass
class Assignment:
    """Result of #6.2: one candidate per slot (hook/develop/close), plus warnings."""

    hook: dict
    develop: list[dict]  # in order s1..sk, one per develop slot
    close: dict
    warnings: list[str] = field(default_factory=list)


def assign_slots(
    slots: list[dict],
    selected: list[dict],
    candidates_by_id: dict,
    config: dict | None = None,
) -> Assignment:
    """Assign one candidate from `selected` to each slot (hook/develop/close), per #6.2.

    Args:
        slots: Slot dicts, as in `slots.json["slots"]` (each with `slot`,
            `start_f`, `end_f`, `role`, `beats_rel_f`).
        selected: Candidate selections, as returned by
            `selection.build_selected` (see `select_develop` for the entry
            shape).
        candidates_by_id: Mapping `candidate_id -> candidate dict`.
        config: Planner config overrides, merged over `DEFAULT_CONFIG`.

    Returns:
        `Assignment` with the chosen hook/develop/close entries and any
        warnings (currently only `"arc_fallback"`, see `place_develop_arc`).

    Raises:
        PlannerError: If no admissible candidate exists for the hook or
            close slot, or fewer develop candidates were taken than there
            are develop slots (the rules fallback for these cases is out
            of this module's scope; it lives in `selection.py`).
    """
    config = {**DEFAULT_CONFIG, **(config or {})}
    hook_slot = next(s for s in slots if s["role"] == "hook")
    close_slot = next(s for s in slots if s["role"] == "close")
    develop_slots = [s for s in slots if s["role"] == "develop"]

    hook = _select_single(
        selected,
        "hook",
        {"peak"},
        candidates_by_id,
        hook_slot["end_f"] - hook_slot["start_f"],
        config["hook_speed"],
    )
    if hook is None:
        msg = "no admissible hook candidate (rules fallback out of scope here)"
        raise PlannerError(msg)

    # "peak" included because fallback_close (#8.6) uses it as a last
    # resort (close_not_calm) when no calm/image candidate is admissible.
    close = _select_single(
        selected,
        "close",
        {"calm", "image", "peak"},
        candidates_by_id,
        close_slot["end_f"] - close_slot["start_f"],
        1.0,
    )
    if close is None:
        msg = "no admissible close candidate (rules fallback out of scope here)"
        raise PlannerError(msg)

    used = [
        {
            "src": candidates_by_id[hook["candidate_id"]]["src"],
            **{
                k: v
                for k, v in compute_in_out(
                    candidates_by_id[hook["candidate_id"]],
                    hook_slot,
                    "hook",
                    config["hook_speed"],
                    config,
                ).items()
                if k in ("in_s", "out_s")
            },
        }
    ]

    taken = select_develop(selected, candidates_by_id, develop_slots, used, config)
    warnings = []
    if len(taken) < len(develop_slots):
        msg = (
            f"not enough develop candidates ({len(taken)}/{len(develop_slots)}); "
            "rules fallback out of this module's scope"
        )
        raise PlannerError(
            msg,
        )

    placement, arc_fallback = place_develop_arc(taken, hook, close, candidates_by_id)
    if arc_fallback:
        warnings.append("arc_fallback")

    return Assignment(hook=hook, develop=placement, close=close, warnings=warnings)
