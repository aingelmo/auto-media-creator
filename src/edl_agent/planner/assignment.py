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

from edl_agent.planner._common import (
    DEFAULT_CONFIG,
    FPS,
    PlannerError,
    admits,
    hook_ramp,
)
from edl_agent.planner.timing import compute_in_out


def _norm_exercise(exercise: str) -> str:
    return exercise.lower().strip()


def _longest_window(
    selected: list[dict],
    candidates_by_id: dict,
    role: str,
    kinds: set[str] | None,
) -> tuple[str, float] | None:
    """Longest candidate window among `selected` entries for a role.

    Args:
        selected: Selection entries (see `select_develop` for the shape).
        candidates_by_id: Mapping `candidate_id -> candidate dict` with a
            `window` key (`(start_s, end_s)` in seconds) and a `kind` key.
        role: Role to filter `selected` by.
        kinds: Candidate kinds to include, or `None` for all kinds.

    Returns:
        `(candidate_id, duration_s)` of the longest window, or `None`
        if no entry matches.
    """
    best: tuple[str, float] | None = None
    for s in selected:
        if s["role"] != role:
            continue
        cand = candidates_by_id.get(s["candidate_id"])
        if cand is None:
            continue
        if kinds is not None and cand["kind"] not in kinds:
            continue
        dur_s = cand["window"][1] - cand["window"][0]
        if best is None or dur_s > best[1]:
            best = (s["candidate_id"], dur_s)
    return best


def _no_admissible_msg(
    role: str,
    slot: dict,
    selected: list[dict],
    candidates_by_id: dict,
    kinds: set[str] | None,
) -> str:
    """Build an actionable error for a role with no admissible candidate.

    The failure is a footage/music mismatch (no window long enough for
    the slot, per #6.1), not a planner bug, so the message carries the
    numbers needed to unblock it instead of an internal-only note.

    Args:
        role: Role with no admissible candidate (`"hook"`/`"close"`).
        slot: Slot dict with `slot`, `start_f`, `end_f`.
        selected: Selection entries (see `select_develop` for the shape).
        candidates_by_id: Mapping `candidate_id -> candidate dict`.
        kinds: Kinds admissible for the role (`{"peak"}` for hook,
            `{"calm", "image", "peak"}` for close).

    Returns:
        Message with the slot duration, the needed window length, how
        many selection entries exist for the role and how many admit
        the slot, the longest available window, and how to unblock.
    """
    d_f = slot["end_f"] - slot["start_f"]
    need_s = d_f / FPS + 2 / FPS
    pool = [
        s
        for s in selected
        if s["role"] == role
        and (
            kinds is None
            or candidates_by_id.get(s["candidate_id"], {}).get("kind")
            in kinds
        )
    ]
    n_admit = sum(
        1
        for s in pool
        if admits(
            tuple(candidates_by_id[s["candidate_id"]]["window"]), d_f, 1.0
        )
    )
    longest = _longest_window(selected, candidates_by_id, role, kinds)
    kinds_s = "/".join(sorted(kinds)) if kinds else "any"
    if longest is None:
        # The LLM pick (if any) was already dropped by S5 and the rules
        # fallback found nothing either, so `selected` holds no entry
        # for this role -- report the longest window across *all*
        # candidates so the message still shows how far off the
        # footage is.
        best_all: tuple[str, float] | None = None
        for cid, cand in candidates_by_id.items():
            if kinds is not None and cand.get("kind") not in kinds:
                continue
            window = cand.get("window")
            if not window:
                continue
            dur_s = window[1] - window[0]
            if best_all is None or dur_s > best_all[1]:
                best_all = (cid, dur_s)
        if best_all is None:
            longest_s = "no candidate of this kind exists at all"
        else:
            longest_s = (
                f"longest {kinds_s} window anywhere is "
                f"{best_all[1]:.2f}s ({best_all[0]}), "
                "already rejected or inadmissible"
            )
    else:
        longest_s = f"longest available is {longest[1]:.2f}s ({longest[0]})"
    return (
        f"no admissible {role} candidate for slot {slot['slot']} "
        f"({d_f} frames, needs a >={need_s:.2f}s {kinds_s} window; "
        f"{longest_s}; {n_admit}/{len(pool)} selection entries "
        "admit the slot). Unblock: shorten the music cut so the slot "
        "fits the available windows, or add footage with a longer "
        f"{kinds_s} moment."
    )


def _select_single(
    selected: list[dict],
    role: str,
    kinds: set[str] | None,
    candidates_by_id: dict,
    slot: dict,
    ramp: dict | None,
    config: dict,
    used: list[dict],
) -> dict | None:
    d_f = slot["end_f"] - slot["start_f"]
    # A ramp only ever needs *less* source than 1.0x, so admitting at 1.0 is
    # conservative and correct.
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
        if not admits(tuple(cand["window"]), d_f, 1.0):
            continue
        if cand["kind"] == "image":
            return s
        timing = compute_in_out(cand, slot, role, ramp, config)
        if not _overlaps_used(
            cand, timing["in_s"], timing["out_s"], used, config["adjacency_gap_s"]
        ):
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
    free_slots: list[dict],
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

    `free_slots` holds the real develop slot dicts (with their real
    `beats_rel_f`), not just durations: the anti-overlap check needs
    `compute_in_out`'s actual beat-aligned `in_s`/`out_s`, or it drifts
    from what `build_clips` computes later for the real slot and can
    let a same-source overlap through undetected (P7).
    """
    free_slots = list(free_slots)
    used = list(used)
    taken: list[dict] = []
    prev_exercise: str | None = None
    prev_src: str | None = None
    for s in pool:
        if len(taken) >= k:
            break
        cand = candidates_by_id[s["candidate_id"]]
        admissible_slots = [
            sl
            for sl in free_slots
            if admits(tuple(cand["window"]), sl["end_f"] - sl["start_f"], 1.0)
        ]
        if not admissible_slots:
            continue
        exercise = _norm_exercise(s["exercise"])
        # "unknown" (rules-fallback, #8.6), "other" (selector's own
        # catch-all, selector/prompts.py), and a "baja"-confidence label
        # (selector unsure which of two movements it is, #5.5) all mean "no
        # reliable exercise label"; treating repeats of any of these as a
        # clash would collapse the unlabeled pool down to a single entry.
        unreliable = exercise in ("unknown", "other") or s.get(
            "exercise_confidence"
        ) == "baja"
        if (
            not allow_exercise_repeat
            and prev_exercise is not None
            and exercise == prev_exercise
            and not unreliable
        ):
            continue
        if not allow_src_repeat and prev_src is not None and cand["src"] == prev_src:
            continue
        # Different admissible slots have different beat-aligned timing
        # (P7), so a candidate that overlaps `used` against one slot may
        # not against another -- try them all before giving up on it.
        admissible_slot = None
        timing = None
        for sl in admissible_slots:
            candidate_timing = compute_in_out(
                cand, sl, role="develop", ramp=None, config=config
            )
            if not _overlaps_used(
                cand, candidate_timing["in_s"], candidate_timing["out_s"], used, gap_s
            ):
                admissible_slot, timing = sl, candidate_timing
                break
        if admissible_slot is None or timing is None:
            continue
        taken.append(s)
        used.append(
            {"src": cand["src"], "in_s": timing["in_s"], "out_s": timing["out_s"]}
        )
        free_slots.remove(admissible_slot)
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
    free_slots = list(develop_slots)

    def _slot_options(s: dict) -> int:
        window = tuple(candidates_by_id[s["candidate_id"]]["window"])
        return sum(
            1
            for sl in develop_slots
            if admits(window, sl["end_f"] - sl["start_f"], 1.0)
        )

    # Most-constrained-first: a candidate whose window fits few slots must be
    # placed before a flexible one grabs its only option (#P7-style greedy
    # order bug -- a wide-window, high-rank candidate would otherwise starve
    # a tight-window, lower-rank one out of its single viable slot).
    pool = sorted(
        (s for s in selected if s["role"] == "develop"),
        key=lambda s: (_slot_options(s), s["rank"]),
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
            free_slots,
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
    # `pool` is constrained-first for packing, but callers (place_develop_arc)
    # expect `taken` in rank order.
    return sorted(taken, key=lambda s: s["rank"])


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


def _fits(entry: dict, slot: dict, candidates_by_id: dict) -> bool:
    window = tuple(candidates_by_id[entry["candidate_id"]]["window"])
    return admits(window, slot["end_f"] - slot["start_f"], 1.0)


def _fit_to_slots(
    taken: list[dict], develop_slots: list[dict], candidates_by_id: dict
) -> list[dict]:
    """Match `taken` to `develop_slots` by duration fit, most-constrained-first.

    `admits` is monotonic in slot duration (a candidate that admits a long
    slot admits every shorter one too), so this greedy always finds a
    matching -- `taken` was chosen by `select_develop` precisely because
    one exists.
    """

    def n_options(s: dict) -> int:
        return sum(1 for sl in develop_slots if _fits(s, sl, candidates_by_id))

    free_slots = list(develop_slots)
    placement: dict[int, dict] = {}
    for s in sorted(taken, key=n_options):
        sl = next(sl for sl in free_slots if _fits(s, sl, candidates_by_id))
        placement[sl["slot"]] = s
        free_slots.remove(sl)
    return [placement[sl["slot"]] for sl in develop_slots]


def place_develop_arc(
    taken: list[dict],
    hook: dict | None,
    close: dict | None,
    candidates_by_id: dict,
    develop_slots: list[dict],
) -> tuple[list[dict], bool]:
    """Place the `taken` develop entries into slot order, per #6.2.4.

    Starts from `arc_order(k)`, then repairs duration mismatches (a
    candidate's window must admit the slot it lands in, P3) by swapping
    entries between slots, and repairs up to 3 adjacency violations
    (neighbors, including the hook before and the close after, repeating
    an exercise or source) the same way -- both repairs only swap entries
    when it doesn't break the other's duration fit. If either kind of
    violation can't be fixed by swapping, falls back to a duration-safe
    slot assignment in rank order.

    Args:
        taken: Develop entries selected by `select_develop`, already
            sorted by rank (rank 1 = best, at index 0).
        hook: The entry placed in the hook slot (or `None`), used only to
            check adjacency against the first develop slot.
        close: The entry placed in the close slot (or `None`), used only to
            check adjacency against the last develop slot.
        candidates_by_id: Mapping `candidate_id -> candidate dict`.
        develop_slots: The develop slot dicts, in slot order (s1..sk).

    Returns:
        `(placement, arc_fallback)`: `placement` is `taken` reordered for
        slots s1..sk; `arc_fallback` is `True` if no arc arrangement was
        found and `placement` falls back to a duration-safe rank-ordered
        assignment (caller should add an `"arc_fallback"` warning in that
        case).
    """
    k = len(taken)
    if k == 0:
        return [], False
    by_rank = {
        i + 1: s for i, s in enumerate(taken)
    }  # taken is already sorted by rank
    order = arc_order(k)
    placement = [by_rank[r] for r in order]

    def duration_violations(p: list[dict]) -> list[int]:
        return [
            i
            for i, (entry, slot) in enumerate(zip(p, develop_slots, strict=True))
            if not _fits(entry, slot, candidates_by_id)
        ]

    for _ in range(k):
        bad = duration_violations(placement)
        if not bad:
            break
        i = bad[0]
        j = next(
            (
                j
                for j in range(k)
                if j != i
                and _fits(placement[i], develop_slots[j], candidates_by_id)
                and _fits(placement[j], develop_slots[i], candidates_by_id)
            ),
            None,
        )
        if j is None:
            return _fit_to_slots(taken, develop_slots, candidates_by_id), True
        placement[i], placement[j] = placement[j], placement[i]

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
        if (
            dev_i >= 0
            and dev_i + 1 < len(placement)
            and _fits(placement[dev_i], develop_slots[dev_i + 1], candidates_by_id)
            and _fits(placement[dev_i + 1], develop_slots[dev_i], candidates_by_id)
        ):
            placement[dev_i], placement[dev_i + 1] = (
                placement[dev_i + 1],
                placement[dev_i],
            )
        else:
            # only one develop slot, or the swap would break duration fit
            break

    chain = [hook, *placement, close]
    if _adjacency_violations(chain, candidates_by_id):
        # #6.2.4: rank order, but still duration-safe; warning: arc_fallback
        return _fit_to_slots(taken, develop_slots, candidates_by_id), True
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
            are develop slots. The message carries the slot duration,
            the needed window length, and the longest available window
            (a footage/music mismatch per #6.1, not a planner bug); the
            rules fallback for these cases lives in `selection.py` and
            already ran before this module (see the module docstring).
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
        hook_slot,
        hook_ramp(config),
        config,
        [],
    )
    if hook is None:
        raise PlannerError(
            _no_admissible_msg(
                "hook", hook_slot, selected, candidates_by_id, {"peak"}
            )
        )

    used = [
        {
            "src": candidates_by_id[hook["candidate_id"]]["src"],
            **{
                k: v
                for k, v in compute_in_out(
                    candidates_by_id[hook["candidate_id"]],
                    hook_slot,
                    "hook",
                    hook_ramp(config),
                    config,
                ).items()
                if k in ("in_s", "out_s")
            },
        }
    ]

    # "peak" included because fallback_close (#8.6) uses it as a last
    # resort (close_not_calm) when no calm/image candidate is admissible.
    close = _select_single(
        selected,
        "close",
        {"calm", "image", "peak"},
        candidates_by_id,
        close_slot,
        None,
        config,
        used,
    )
    if close is None:
        raise PlannerError(
            _no_admissible_msg(
                "close",
                close_slot,
                selected,
                candidates_by_id,
                {"calm", "image", "peak"},
            )
        )

    if candidates_by_id[close["candidate_id"]]["kind"] != "image":
        close_timing = compute_in_out(
            candidates_by_id[close["candidate_id"]], close_slot, "close", None, config
        )
        used = [
            *used,
            {
                "src": candidates_by_id[close["candidate_id"]]["src"],
                "in_s": close_timing["in_s"],
                "out_s": close_timing["out_s"],
            },
        ]

    taken = select_develop(selected, candidates_by_id, develop_slots, used, config)
    warnings = []
    if len(taken) < len(develop_slots):
        msg = (
            f"not enough develop candidates ({len(taken)}/"
            f"{len(develop_slots)} slots admit their windows; "
            "footage/music mismatch per #6.1, not a planner bug). "
            "Unblock: shorten the music cut or add longer peak footage."
        )
        raise PlannerError(msg)

    placement, arc_fallback = place_develop_arc(
        taken, hook, close, candidates_by_id, develop_slots
    )
    if arc_fallback:
        warnings.append("arc_fallback")

    return Assignment(hook=hook, develop=placement, close=close, warnings=warnings)
