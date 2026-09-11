"""Capa 5 - S-checks (#8.1) y fallback de reglas (#8.6).

Reconcilia una `selection.json` (LLM) contra `candidates.json` y completa,
rol a rol, los huecos con el fallback de reglas de 0 EUR. Produce la lista
`selected` que consume `planner.assign_slots`. Si no hay seleccion del LLM
(``selection is None``), todo el resultado viene del fallback.
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
# 8.1 S-checks sobre selection.json
# --------------------------------------------------------------------------

def apply_s_checks(
    selection: dict, candidates_by_id: dict, slots: list[dict],
) -> tuple[list[dict], list[str]]:
    """S2-S5. S1 (status incomplete) se resuelve fuera de esta funcion (cosa
    del llamador del LLM); los huecos por rol que deje S5 los cubre el
    fallback en `build_selected`."""
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

    # S5: el LLM no conoce `admits_slots` (no se le envia); descarta aqui lo
    # que eligio para un rol cuyo(s) slot(s) no caben en su ventana, para que
    # el fallback de `build_selected` pueda cubrir ese hueco.
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
# 8.6 Fallback de reglas, por rol
# --------------------------------------------------------------------------

def fallback_hook(candidates: list[dict], slot_indices: list[int], used_ids: set[str]) -> dict | None:
    pool = [
        c for c in candidates
        if c["kind"] == "peak" and c["id"] not in used_ids and _admits(c, slot_indices)
        and c["motion_bg"] <= FALLBACK_HOOK_MOTION_BG_MAX
        and c["sharpness"] >= FALLBACK_HOOK_SHARPNESS_MIN
    ]
    if not pool:
        return None
    single_subject = [c for c in pool if not c["multi_subject"]]
    pool = single_subject or pool
    best = max(pool, key=lambda c: c["kp_speed"])
    return {"candidate_id": best["id"], "role": "hook", "rank": 1, "exercise": "unknown", "reason": "rules_fallback"}


def fallback_close(candidates: list[dict], slot_indices: list[int], used_ids: set[str]) -> tuple[dict | None, list[str]]:
    def admissible(kinds: set[str]) -> list[dict]:
        return [
            c for c in candidates
            if c["kind"] in kinds and c["id"] not in used_ids and _admits(c, slot_indices)
        ]

    calm = admissible({"calm"})
    if calm:
        best = max(calm, key=lambda c: c["sharpness"] * _centrality(c["subject_bbox"]))
        return {"candidate_id": best["id"], "role": "close", "rank": 1,
                "exercise": "unknown", "reason": "rules_fallback"}, []

    images = admissible({"image"})
    if images:
        best = max(images, key=lambda c: c["score_cv"])
        return {"candidate_id": best["id"], "role": "close", "rank": 1,
                "exercise": "unknown", "reason": "rules_fallback"}, []

    peaks = admissible({"peak"})
    if peaks:
        best = min(peaks, key=lambda c: c["kp_speed"])
        return {"candidate_id": best["id"], "role": "close", "rank": 1,
                "exercise": "unknown", "reason": "rules_fallback"}, ["close_not_calm"]

    return None, []


def fallback_develop(candidates: list[dict], slot_indices: list[int], used_ids: set[str], k: int) -> list[dict]:
    pool = sorted(
        (c for c in candidates
         if c["kind"] == "peak" and c["id"] not in used_ids and _admits(c, slot_indices)),
        key=lambda c: c["score_cv"], reverse=True,
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
        {"candidate_id": c["id"], "role": "develop", "rank": i + 1,
         "exercise": "unknown", "reason": "rules_fallback"}
        for i, c in enumerate(ordered)
    ]


# --------------------------------------------------------------------------
# 8.5 Orquestacion: S-checks + fallback -> `selected` para el planner
# --------------------------------------------------------------------------

def _preempt_develop(cleaned: list[dict], candidate_id: str, warnings: list[str], role: str) -> list[dict]:
    """Un candidato ya asignado a develop pasa a `role` (hook/close): develop
    tiene mas slack (N slots, mas candidatos tipicamente) que hook/close
    (obligatorios, 1 slot). El hueco que deja se rellena luego con
    `fallback_develop` sobre el pool restante."""
    warnings.append(f"{role}_preempted_develop:{candidate_id}")
    return [e for e in cleaned if not (e["role"] == "develop" and e["candidate_id"] == candidate_id)]


def build_selected(
    candidates_json: dict, slots_json: dict, selection: dict | None = None,
) -> tuple[list[dict], list[str], list[str]]:
    """Devuelve (selected, warnings, fallback_roles)."""
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
        entry = fallback_hook(candidates, _slot_indices(slots, "hook"), used_ids)
        if entry is None:
            # #6.2.5: nada libre admite hook; reclama lo que develop tenga admisible.
            develop_ids = {e["candidate_id"] for e in cleaned if e["role"] == "develop"}
            entry = fallback_hook(candidates, _slot_indices(slots, "hook"), used_ids - develop_ids)
            if entry:
                cleaned = _preempt_develop(cleaned, entry["candidate_id"], warnings, "hook")
        if entry:
            cleaned.append(entry)
            used_ids.add(entry["candidate_id"])
            fallback_roles.append("hook")

    if not any(e["role"] == "close" for e in cleaned):
        entry, close_warnings = fallback_close(candidates, _slot_indices(slots, "close"), used_ids)
        if entry is None:
            develop_ids = {e["candidate_id"] for e in cleaned if e["role"] == "develop"}
            entry, close_warnings = fallback_close(candidates, _slot_indices(slots, "close"), used_ids - develop_ids)
            if entry:
                cleaned = _preempt_develop(cleaned, entry["candidate_id"], warnings, "close")
        warnings.extend(close_warnings)
        if entry:
            cleaned.append(entry)
            used_ids.add(entry["candidate_id"])
            fallback_roles.append("close")

    develop_count = sum(1 for e in cleaned if e["role"] == "develop")
    if develop_k > 0 and develop_count < develop_k:
        extra = fallback_develop(candidates, _slot_indices(slots, "develop"), used_ids, develop_k - develop_count)
        for i, entry in enumerate(extra):
            entry["rank"] = develop_count + i + 1
        cleaned.extend(extra)
        used_ids.update(e["candidate_id"] for e in extra)
        if "develop" not in fallback_roles:
            fallback_roles.append("develop")

    return cleaned, warnings, fallback_roles
