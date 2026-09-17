"""8.1 S-checks on selection.json."""

from __future__ import annotations

import re

from edl_agent.selection._common import ROLES, _admits, _slot_indices

HOOK_LINE_MAX_WORDS = 8  # operator-typed text (strict=False)
HOOK_LINE_MIN_WORDS = 3
HOOK_LINE_STRICT_MAX_WORDS = 8
HOOK_LINE_MAX_CHARS = 48

# Substrings (casefold) that mark a line as an invented slogan rather than a
# description of what's on screen.
GENERIC_PHRASES: tuple[str, ...] = (
    "sin excusas",
    "dalo todo",
    "a otro nivel",
    "modo bestia",
    "el límite",
    "sin límites",
    "no pain",
    "no hay excusas",
    "puedes con todo",
    "nunca te rindas",
    "así empieza",
    "hoy toca",
    "una más",
    "vamos",
    "reto",
    "récord",
    "transforma tu cuerpo",
    "quema grasa",
    "sin dolor",
    "dolor",
    "lesión",
)


def numbers_in(text: str) -> frozenset[str]:
    """Digit substrings appearing verbatim in `text`.

    Used as `clean_hook_line`'s `allowed_numbers` (numbers from an operator
    brief are grounded, not invented).
    """
    return frozenset(re.findall(r"\d+", text))


def clean_hook_line(
    raw: object, strict: bool = False, allowed_numbers: frozenset[str] = frozenset()
) -> str:
    """Trim/unquote/validate a hook line; `""` if it fails any check.

    Always applied: strip whitespace/quotes, drop a trailing `.`/`!`
    (a trailing `?` is kept -- questions are an allowed hook device, #5.7),
    reject if empty, contains `#`/`@`, any character outside the es-ES
    text/punctuation range (`ord > 0x2000`, which catches emoji), or longer
    than `HOOK_LINE_MAX_CHARS` (rejected outright rather than truncated --
    a hard cut mid-word, e.g. "kettlebells al lad", is worse than asking
    for a shorter line).

    `strict=True` (LLM output, #5.7) additionally rejects: fewer than
    `HOOK_LINE_MIN_WORDS` or more than `HOOK_LINE_STRICT_MAX_WORDS` words,
    any digit not in `allowed_numbers` (invented reps/kg/times, unless it
    appeared verbatim in the operator's brief or the reel context, see
    `numbers_in`), or a substring from `GENERIC_PHRASES` (invented slogan).

    `strict=False` (operator-typed text, `hook_custom` in the web form)
    keeps the looser 1-`HOOK_LINE_MAX_WORDS`-word check only.
    """
    line = str(raw or "").strip().strip("\"'“”«»").strip().rstrip(".!").strip()
    words = line.split()
    unlisted_digits = any(n not in allowed_numbers for n in re.findall(r"\d+", line))

    rejected = (
        not line
        or "#" in line
        or "@" in line
        or len(line) > HOOK_LINE_MAX_CHARS
        or any(ord(ch) > 0x2000 for ch in line)
        or (
            not HOOK_LINE_MIN_WORDS <= len(words) <= HOOK_LINE_STRICT_MAX_WORDS
            or unlisted_digits
            or any(phrase in line.casefold() for phrase in GENERIC_PHRASES)
            if strict
            else not 0 < len(words) <= HOOK_LINE_MAX_WORDS
        )
    )
    return "" if rejected else line


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
          `"s2_dropped:{id}"` (unknown or duplicate candidate_id, or a
          same-role candidate sharing another candidate's src+window --
          same physical footage under a different id, e.g. one candidate
          per subject bbox in a multi-subject scene),
          `"s4_moved:{id}->close"` (role reassigned because a non-`peak`
          candidate was picked for hook, which must be `peak`), or
          `"s5_dropped:{id}"` (candidate's window doesn't admit any slot
          of its assigned role). `close` may
          be `peak`-kind: the prompt already tells the model to prefer
          calm/image there and only use a still-looking peak as a last
          resort, so its own rank ordering
          is trusted instead of a hard kind filter.
    """
    warnings: list[str] = []
    seen: set[str] = set()
    seen_footage: set[tuple[str, str, tuple]] = set()
    cleaned: list[dict] = []

    for entry in selection.get("selected", []):
        cid = entry.get("candidate_id")
        if cid not in candidates_by_id or cid in seen:
            warnings.append(f"s2_dropped:{cid}")
            continue
        cand = candidates_by_id[cid]
        footage = (entry.get("role"), cand["src"], tuple(cand["window"]))
        if footage in seen_footage:
            warnings.append(f"s2_dropped:{cid}")
            continue
        seen.add(cid)
        seen_footage.add(footage)
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

    by_role: dict[str, list[dict]] = {role: [] for role in ROLES}
    for entry in cleaned:
        by_role[entry["role"]].append(entry)
    for entries in by_role.values():
        for i, entry in enumerate(entries, start=1):
            entry["rank"] = i

    return [e for role in ROLES for e in by_role[role]], warnings
