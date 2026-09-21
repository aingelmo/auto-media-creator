"""#6 Planner determinista. Property tests P1-P9 (#8.2) sobre candidatos
sinteticos, con fuentes de varios aspect ratios (16:9, 4:3, 9:16, 9:19.5, 1:1).
"""

from __future__ import annotations

import itertools
import random

import pytest

from edl_agent.planner import (
    DEFAULT_CONFIG,
    PlannerError,
    admits,
    arc_order,
    assign_slots,
    build_clips,
    compute_in_out,
    place_develop_arc,
    select_develop,
)

FPS = 30


def _slots(n_develop: int, hook_f=45, develop_f=40, close_f=60):
    slots = [
        {
            "slot": 0,
            "start_f": 0,
            "end_f": hook_f,
            "role": "hook",
            "beats_rel_f": [0, hook_f // 2],
        }
    ]
    start = hook_f
    for i in range(n_develop):
        slots.append(
            {
                "slot": i + 1,
                "start_f": start,
                "end_f": start + develop_f,
                "role": "develop",
                "beats_rel_f": [0, develop_f // 2],
            }
        )
        start += develop_f
    slots.append(
        {
            "slot": n_develop + 1,
            "start_f": start,
            "end_f": start + close_f,
            "role": "close",
            "beats_rel_f": [0, close_f // 2],
        }
    )
    return slots


def _source(src, w, h, hdr="none", rotation=0, duration_s=20.0):
    return {
        "src": src,
        "sha256": f"sha-{src}",
        "type": "video",
        "w": w,
        "h": h,
        "rotation": rotation,
        "hdr": hdr,
        "duration_s": duration_s,
        "color": {
            "primaries": "bt709",
            "trc": "bt709",
            "space": "bt709",
            "range": "tv",
        },
    }


def _candidate(cid, src, kind, t_peak, window, bbox=(0.3, 0.1, 0.7, 0.9)):
    return {
        "id": cid,
        "src": src,
        "kind": kind,
        "t_peak": t_peak,
        "window": list(window),
        "subject_bbox": list(bbox),
    }


def _selected(cid, role, rank, exercise="back squat"):
    return {
        "candidate_id": cid,
        "role": role,
        "rank": rank,
        "exercise": exercise,
        "reason": "test",
    }


ASPECTS = [
    ("16:9", 1920, 1080),
    ("4:3", 1280, 960),
    ("9:16", 1080, 1920),
    ("9:19.5", 1080, 2340),
    ("1:1", 1000, 1000),
]


def _build_scenario(n_develop: int, aspect_dims: tuple[int, int], seed: int):
    rng = random.Random(seed)
    w, h = aspect_dims
    slots = _slots(n_develop)

    sources_by_src = {}
    candidates_by_id = {}
    selected = []

    # Distinct exercise labels from the develop cycle below (#6.2.4 arc
    # repair is exercised separately, in test_place_develop_arc_*), so this
    # scenario has no adjacency violations to begin with.
    hook_id = "hook0"
    sources_by_src["hook.mov"] = _source("hook.mov", w, h)
    candidates_by_id[hook_id] = _candidate(
        hook_id, "hook.mov", "peak", t_peak=1.0, window=(0.0, 5.0)
    )
    selected.append(_selected(hook_id, "hook", 1, exercise="hook_move"))

    close_id = "close0"
    sources_by_src["close.mov"] = _source("close.mov", w, h)
    candidates_by_id[close_id] = _candidate(
        close_id, "close.mov", "calm", t_peak=5.0, window=(3.0, 8.0)
    )
    selected.append(_selected(close_id, "close", 1, exercise="close_move"))

    exercises = [
        "back squat",
        "deadlift",
        "clean",
        "snatch",
        "pull-up",
        "burpee",
        "thruster",
        "jerk",
    ]
    for i in range(n_develop):
        cid = f"dev{i}"
        src = f"dev{i}.mov"
        sources_by_src[src] = _source(src, w, h)
        t_peak = rng.uniform(5.0, 9.0)
        window = (max(0.0, t_peak - 4.0), t_peak + 4.0)
        bbox = (
            rng.uniform(0.1, 0.3),
            rng.uniform(0.05, 0.2),
            rng.uniform(0.6, 0.9),
            rng.uniform(0.7, 0.95),
        )
        candidates_by_id[cid] = _candidate(cid, src, "peak", t_peak, window, bbox)
        selected.append(
            _selected(cid, "develop", i + 1, exercise=exercises[i % len(exercises)])
        )

    return slots, selected, candidates_by_id, sources_by_src


def test_hook_line_override_is_used() -> None:
    slots, selected, candidates_by_id, sources_by_src = _build_scenario(
        2, (1920, 1080), seed=0
    )
    clips, _ = build_clips(
        slots,
        selected,
        candidates_by_id,
        sources_by_src,
        {"hook_line_override": "Del operador"},
    )
    assert clips[0]["effect_params"]["text"] == "DEL\\NOPERADOR"


def test_hook_copy_propagates_to_effect_params() -> None:
    slots, selected, candidates_by_id, sources_by_src = _build_scenario(
        2, (1920, 1080), seed=0
    )
    clips, _ = build_clips(
        slots,
        selected,
        candidates_by_id,
        sources_by_src,
        {"hook_line_override": "La barra despega del suelo"},
    )
    hook_clip = clips[0]
    assert hook_clip["effect_params"]["text"] == "LA BARRA DESPEGA\\NDEL SUELO"
    assert "text_frames" in hook_clip["effect_params"]
    assert "fade_frames" in hook_clip["effect_params"]


def test_hook_copy_abstention_leaves_no_text_overlay() -> None:
    slots, selected, candidates_by_id, sources_by_src = _build_scenario(
        2, (1920, 1080), seed=0
    )
    clips, _ = build_clips(
        slots,
        selected,
        candidates_by_id,
        sources_by_src,
        {"hook_line_override": ""},
    )
    assert "text" not in clips[0]["effect_params"]


def test_punch_every_skips_develop_cuts() -> None:
    slots, selected, candidates_by_id, sources_by_src = _build_scenario(
        4, (1920, 1080), seed=2
    )
    clips, _ = build_clips(
        slots,
        selected,
        candidates_by_id,
        sources_by_src,
        {"punch_every": 2, "punch_in": True},
    )
    develop_clips = [c for c in clips if c["role"] == "develop"]
    for i, c in enumerate(develop_clips):
        if i % 2 == 0:
            assert "punch_frames" in c["effect_params"]
        else:
            assert "punch_frames" not in c["effect_params"]


_BRAND = {
    "logo": "brand/logo.png",
    "logo_sha256": "x",
    "logo_w": 200,
    "logo_h": 80,
    "handle": "@gym",
    "bg": "#111111",
    "fg": "#FFFFFF",
    "font": DEFAULT_CONFIG["hook_text_font"],
}


@pytest.mark.parametrize("close_f", [35, 60, 90])
def test_outro_annotates_close_tail_without_stealing_frames(close_f) -> None:
    slots, selected, candidates_by_id, sources_by_src = _build_scenario(
        2, (1920, 1080), seed=1
    )
    slots = _slots(2, close_f=close_f)
    clips, warnings = build_clips(
        slots, selected, candidates_by_id, sources_by_src, brand=_BRAND
    )
    # No synthetic clip: one clip per slot, timeline untouched, never skipped.
    assert len(clips) == len(slots)
    assert "end_card_skipped" not in warnings
    assert sum(c["n_frames"] for c in clips) == slots[-1]["end_f"]
    close = clips[-1]
    assert close["role"] == "close" and close["n_frames"] == close_f
    p = close["effect_params"]
    assert p["outro_frames"] == min(DEFAULT_CONFIG["end_card_frames"], close_f)
    assert p["outro_handle"] == _BRAND["handle"]
    assert p["outro_logo_src"] == _BRAND["logo"]
    assert p["outro_logo_w"] == DEFAULT_CONFIG["end_card_logo_w"]
    assert p["outro_logo_h"] == 144  # 360 * 80 / 200
    assert p["outro_text_size"] == DEFAULT_CONFIG["end_card_text_size"]


def test_no_outro_without_brand() -> None:
    slots, selected, candidates_by_id, sources_by_src = _build_scenario(
        2, (1920, 1080), seed=1
    )
    clips, _ = build_clips(slots, selected, candidates_by_id, sources_by_src)
    assert all("outro_frames" not in c["effect_params"] for c in clips)


@pytest.mark.parametrize(("aspect_name", "w", "h"), ASPECTS)
@pytest.mark.parametrize("n_develop", [1, 2, 4, 5, 6])
def test_planner_invariants(aspect_name, w, h, n_develop) -> None:
    slots, selected, candidates_by_id, sources_by_src = _build_scenario(
        n_develop, (w, h), seed=n_develop * 7
    )
    clips, warnings = build_clips(slots, selected, candidates_by_id, sources_by_src)

    n_slots = n_develop + 2
    # hook_ramp on by default: the hook slot has 2 beats, so it gets a ramp
    assert clips[0]["effect"] == "ramp"
    assert all(c["effect"] != "ramp" for c in clips[1:])
    # P1
    assert len(clips) == n_slots
    assert [c["slot"] for c in clips] == list(range(n_slots))
    # P2
    assert len({c["candidate_id"] for c in clips}) == n_slots
    for c in clips:
        cand = candidates_by_id[c["candidate_id"]]
        if cand["kind"] != "image":
            # P3
            assert cand["window"][0] <= c["in_s"]
            assert c["out_s"] <= cand["window"][1]
            # P4
            assert 0 <= c["in_s"] < c["out_s"]
            # P5 (ramp: its frames consume ramp_speed x source time)
            src_s = c["out_s"] - c["in_s"]
            n_ramp = 0
            if c["effect"] == "ramp":
                n_ramp = c["effect_params"]["ramp_frames"]
                src_s -= n_ramp / FPS * c["effect_params"]["ramp_speed"]
            assert round(src_s * FPS) + n_ramp == c["n_frames"]
            assert c["speed"] == 1.0
        # P8
        crop = c["crop"]
        assert 0 <= crop["x"] <= 1
        assert 0 <= crop["y"] <= 1
        assert 0 < crop["w"] <= 1
        assert 0 < crop["h"] <= 1
        px = c["crop_px"]
        assert px["x"] >= 0
        assert px["x"] + px["w"] <= c["src_w"]
        assert px["y"] >= 0
        assert px["y"] + px["h"] <= c["src_h"]
        assert px["w"] % 2 == 0
        assert px["h"] % 2 == 0
        if c["layout"] == "crop":
            assert abs(px["w"] / px["h"] - 9 / 16) * px["h"] <= 2
        # P9
        assert c["n_frames"] >= 30

    # P6
    assert clips[0]["timeline_start_f"] == 0
    assert clips[-1]["timeline_end_f"] == slots[-1]["end_f"]
    for a, b in itertools.pairwise(clips):
        assert a["timeline_end_f"] == b["timeline_start_f"]
    assert sum(c["n_frames"] for c in clips) == slots[-1]["end_f"]

    # P7: sin solapes de la misma fuente (margen 0.25s)
    by_src: dict[str, list[dict]] = {}
    for c in clips:
        if c["type"] == "image":
            continue
        by_src.setdefault(c["src"], []).append(c)
    for segs in by_src.values():
        ordered = sorted(segs, key=lambda c: c["in_s"])
        for a, b in itertools.pairwise(ordered):
            assert a["out_s"] + 0.25 <= b["in_s"] + 1e-6

    # Arco de develop: el mejor rank de develop (rank=1) queda justo antes del close.
    develop_clips = [c for c in clips if c["role"] == "develop"]
    if develop_clips and "arc_fallback" not in warnings:
        best_rank_id = min(
            (s for s in selected if s["role"] == "develop"),
            key=lambda s: s["rank"],
        )["candidate_id"]
        assert develop_clips[-1]["candidate_id"] == best_rank_id


def test_admits_respects_margin() -> None:
    # d_f=60 -> need_s=2.0s; con margen de 2 frames el umbral es 2.0 + 2/30.
    assert admits((0.0, 2.1), d_f=60, speed=1.0)
    assert not admits((0.0, 2.0), d_f=60, speed=1.0)


def test_arc_order_best_rank_last() -> None:
    for k in range(1, 8):
        order = arc_order(k)
        assert sorted(order) == list(range(1, k + 1))
        assert order[-1] == 1


def test_compute_in_out_peak_lands_on_configured_beat() -> None:
    # #6.3: sin clamp, in_s = t_peak - lead * need_s, con lead =
    # beats_rel_f[peak_beat_index] / d_f.
    slot = {"start_f": 0, "end_f": 60, "beats_rel_f": [0, 20, 40]}  # d_f=60, 2s
    cand = _candidate("c0", "a.mov", "peak", t_peak=6.0, window=(0.0, 12.0))
    timing = compute_in_out(
        cand, slot, role="develop", ramp=None, config=DEFAULT_CONFIG
    )
    assert timing["ramp"] is None

    need_s = 60 / FPS
    lead = 20 / 60  # peak_beat_index=1 -> beats_rel_f[1] == 20
    expected_in_s = 6.0 - lead * need_s
    assert timing["in_s"] == pytest.approx(expected_in_s)
    assert timing["out_s"] == pytest.approx(expected_in_s + need_s)
    assert timing["warnings"] == []

    # El beat cae exactamente en (in_s + lead*need_s) == t_peak.
    beat_offset_s = timing["in_s"] + lead * need_s
    assert beat_offset_s == pytest.approx(cand["t_peak"])


def test_compute_in_out_clamped_reports_peak_off_beat() -> None:
    slot = {"start_f": 0, "end_f": 60, "beats_rel_f": [0, 20, 40]}
    # t_peak muy cerca del borde de la ventana: el lead lo empuja fuera y se clampa.
    cand = _candidate("c0", "a.mov", "peak", t_peak=0.5, window=(0.0, 12.0))
    timing = compute_in_out(
        cand, slot, role="develop", ramp=None, config=DEFAULT_CONFIG
    )
    assert timing["in_s"] == 0.0
    assert "peak_off_beat" in timing["warnings"]


def test_compute_in_out_ramp_peak_on_beat() -> None:
    # d_f=45, peak on beats_rel_f[1]=15 -> ramp of 12 frames centred there
    # (a=9, b=21); source consumed shrinks by 12/30*(1-0.4).
    slot = {"start_f": 0, "end_f": 45, "beats_rel_f": [0, 15, 30]}
    cand = _candidate("c0", "a.mov", "peak", t_peak=6.0, window=(0.0, 12.0))
    timing = compute_in_out(
        cand,
        slot,
        role="hook",
        ramp={"speed": 0.4, "frames": 12},
        config=DEFAULT_CONFIG,
    )
    need_s = (45 - 12) / FPS + 12 / FPS * 0.4
    lead_src_s = 9 / FPS + 6 / FPS * 0.4
    assert timing["in_s"] == pytest.approx(6.0 - lead_src_s)
    assert timing["out_s"] == pytest.approx(6.0 - lead_src_s + need_s)
    assert timing["ramp"] == {"speed": 0.4, "frames": 12, "start_f": 9}
    assert timing["peak_f"] == 15
    assert timing["warnings"] == []

    # Ramp is a no-op on calm candidates and single-beat slots.
    calm = _candidate("c1", "a.mov", "calm", t_peak=6.0, window=(0.0, 12.0))
    assert (
        compute_in_out(
            calm, slot, "close", {"speed": 0.4, "frames": 12}, DEFAULT_CONFIG
        )["ramp"]
        is None
    )
    one_beat = {"start_f": 0, "end_f": 45, "beats_rel_f": [0]}
    assert (
        compute_in_out(
            cand, one_beat, "hook", {"speed": 0.4, "frames": 12}, DEFAULT_CONFIG
        )["ramp"]
        is None
    )


def test_missing_hook_raises() -> None:
    slots = _slots(1)
    selected = [_selected("dev0", "develop", 1), _selected("close0", "close", 1)]
    candidates_by_id = {
        "dev0": _candidate("dev0", "a.mov", "peak", 6.0, (2.0, 10.0)),
        "close0": _candidate("close0", "b.mov", "calm", 6.0, (2.0, 10.0)),
    }
    sources_by_src = {
        "a.mov": _source("a.mov", 1920, 1080),
        "b.mov": _source("b.mov", 1920, 1080),
    }
    with pytest.raises(PlannerError):
        build_clips(slots, selected, candidates_by_id, sources_by_src)


def test_place_develop_arc_repairs_boundary_violation_against_close() -> None:
    # rank1 (best) is always placed last by arc_order, adjacent to close --
    # give it the same exercise as close so that boundary clashes, and
    # verify the fix (mapping the violation to a develop-side swap even at
    # the chain edges) repairs it instead of falling back.
    hook = _selected("hook0", "hook", 1, exercise="hook_move")
    close = _selected("close0", "close", 1, exercise="close_move")
    dev_rank1 = _selected(  # clashes w/ close
        "dev1", "develop", 1, exercise="close_move"
    )
    dev_rank2 = _selected("dev2", "develop", 2, exercise="burpee")
    candidates_by_id = {
        "hook0": _candidate("hook0", "hook.mov", "peak", 1.0, (0.0, 5.0)),
        "close0": _candidate("close0", "close.mov", "calm", 5.0, (3.0, 8.0)),
        "dev1": _candidate("dev1", "dev1.mov", "peak", 5.0, (1.0, 9.0)),
        "dev2": _candidate("dev2", "dev2.mov", "peak", 5.0, (1.0, 9.0)),
    }
    taken = [dev_rank1, dev_rank2]  # sorted by rank, rank1 first

    placement, arc_fallback = place_develop_arc(
        taken, hook, close, candidates_by_id, _develop_slots(2)
    )

    assert arc_fallback is False
    chain = [hook, *placement, close]
    assert not [
        i
        for i in range(len(chain) - 1)
        if chain[i]["exercise"] == chain[i + 1]["exercise"]
    ]
    # rank1 got swapped away from the close boundary to fix the clash.
    assert placement[-1]["candidate_id"] == "dev2"


def test_place_develop_arc_falls_back_when_unrepairable() -> None:
    # A single develop slot has no develop-side neighbor to swap with, so a
    # boundary clash against hook can't be repaired: must fall back, not
    # loop forever or crash.
    hook = _selected("hook0", "hook", 1, exercise="squat")
    close = _selected("close0", "close", 1, exercise="close_move")
    dev = _selected("dev1", "develop", 1, exercise="squat")  # clashes w/ hook
    candidates_by_id = {
        "hook0": _candidate("hook0", "hook.mov", "peak", 1.0, (0.0, 5.0)),
        "close0": _candidate("close0", "close.mov", "calm", 5.0, (3.0, 8.0)),
        "dev1": _candidate("dev1", "dev1.mov", "peak", 5.0, (1.0, 9.0)),
    }

    placement, arc_fallback = place_develop_arc(
        [dev], hook, close, candidates_by_id, _develop_slots(1)
    )

    assert arc_fallback is True
    assert placement == [dev]


def test_place_develop_arc_repairs_duration_violation() -> None:
    # arc_order(3) = [2, 3, 1]: rank2 lands in slot0 first. Give rank2 a
    # window too narrow for slot0's 90 frames but wide enough for the
    # other two (20 frames each) -- the arc placement must swap it into a
    # slot it actually admits (P3), not just fix exercise adjacency.
    develop_slots = [
        {"slot": 1, "start_f": 0, "end_f": 90, "role": "develop", "beats_rel_f": [0]},
        {"slot": 2, "start_f": 90, "end_f": 110, "role": "develop", "beats_rel_f": [0]},
        {
            "slot": 3,
            "start_f": 110,
            "end_f": 130,
            "role": "develop",
            "beats_rel_f": [0],
        },
    ]
    dev_rank1 = _selected("dev1", "develop", 1, exercise="squat")
    dev_rank2 = _selected("dev2", "develop", 2, exercise="burpee")
    dev_rank3 = _selected("dev3", "develop", 3, exercise="lunge")
    candidates_by_id = {
        "dev1": _candidate("dev1", "a.mov", "peak", 5.0, (0.0, 20.0)),
        "dev2": _candidate("dev2", "b.mov", "peak", 5.0, (4.5, 5.5)),  # too narrow
        "dev3": _candidate("dev3", "c.mov", "peak", 5.0, (0.0, 20.0)),
    }
    taken = [dev_rank1, dev_rank2, dev_rank3]

    placement, arc_fallback = place_develop_arc(
        taken, None, None, candidates_by_id, develop_slots
    )

    assert arc_fallback is False
    for entry, slot in zip(placement, develop_slots, strict=True):
        window = candidates_by_id[entry["candidate_id"]]["window"]
        duration_f = slot["end_f"] - slot["start_f"]  # ty: ignore[unsupported-operator]
        assert admits(window, duration_f, 1.0)
    assert {e["candidate_id"] for e in placement} == {"dev1", "dev2", "dev3"}


def _develop_slots(k: int, develop_f: int = 40):
    return [s for s in _slots(k, develop_f=develop_f) if s["role"] == "develop"]


def test_select_develop_stage1_relaxation_allows_repeated_exercise() -> None:
    develop_slots = _develop_slots(3)
    candidates_by_id = {
        "c1": _candidate("c1", "a.mov", "peak", 2.0, (0.0, 4.0)),
        "c2": _candidate("c2", "b.mov", "peak", 2.0, (0.0, 4.0)),
        "c3": _candidate("c3", "c.mov", "peak", 2.0, (0.0, 4.0)),
    }
    selected = [
        _selected("c1", "develop", 1, exercise="squat"),
        _selected("c2", "develop", 2, exercise="squat"),  # repeats c1's exercise
        _selected("c3", "develop", 3, exercise="deadlift"),
    ]

    taken = select_develop(
        selected, candidates_by_id, develop_slots, [], DEFAULT_CONFIG
    )

    assert [s["candidate_id"] for s in taken] == ["c1", "c2", "c3"]


def test_select_develop_stage2_relaxation_allows_repeated_src() -> None:
    develop_slots = _develop_slots(3)
    candidates_by_id = {
        "c1": _candidate("c1", "a.mov", "peak", 2.0, (0.0, 4.0)),
        "c2": _candidate("c2", "a.mov", "peak", 10.0, (8.0, 12.0)),  # repeats c1's src
        "c3": _candidate("c3", "b.mov", "peak", 2.0, (0.0, 4.0)),
    }
    selected = [
        _selected("c1", "develop", 1, exercise="squat"),
        _selected("c2", "develop", 2, exercise="deadlift"),
        _selected("c3", "develop", 3, exercise="clean"),
    ]

    taken = select_develop(
        selected, candidates_by_id, develop_slots, [], DEFAULT_CONFIG
    )

    assert [s["candidate_id"] for s in taken] == ["c1", "c2", "c3"]


def test_select_develop_tries_other_admissible_slots_before_rejecting() -> None:
    # Two develop slots of equal duration but different beat offsets (P7:
    # timing is now beat-aligned per real slot). c1's window only leaves
    # room to avoid `used` when paired with the *second* slot -- the fix
    # must not give up on it just because the first admissible slot's
    # beat-aligned timing collides.
    slots = [
        {"start_f": 40, "end_f": 80, "role": "develop", "beats_rel_f": [0, 35]},
        {"start_f": 0, "end_f": 40, "role": "develop", "beats_rel_f": [0, 5]},
    ]
    candidates_by_id = {
        "c1": _candidate("c1", "a.mov", "peak", 0.7, (0.0, 2.0)),
    }
    selected = [_selected("c1", "develop", 1, exercise="squat")]
    used = [{"src": "a.mov", "in_s": 0.0, "out_s": 0.2}]

    taken = select_develop(selected, candidates_by_id, slots, used, DEFAULT_CONFIG)

    assert [s["candidate_id"] for s in taken] == ["c1"]


def test_select_develop_constrained_first_avoids_starving_tight_candidate() -> None:
    # slot0 is short, slot1 is long. c2's window only admits slot0; c1's
    # window admits both. Rank order alone (c1 first) would let c1 grab
    # slot0 and leave c2 stranded with no admissible slot at all -- the
    # fix must place the tighter-fit candidate first so both land.
    slots = [
        {"start_f": 0, "end_f": 10, "role": "develop", "beats_rel_f": [0]},
        {"start_f": 10, "end_f": 110, "role": "develop", "beats_rel_f": [0]},
    ]
    candidates_by_id = {
        "c1": _candidate("c1", "a.mov", "peak", 2.0, (0.0, 5.0)),  # fits both
        "c2": _candidate("c2", "b.mov", "peak", 0.2, (0.0, 0.5)),  # fits only slot0
    }
    selected = [
        _selected("c1", "develop", 1, exercise="squat"),
        _selected("c2", "develop", 2, exercise="deadlift"),
    ]

    taken = select_develop(selected, candidates_by_id, slots, [], DEFAULT_CONFIG)

    assert {s["candidate_id"] for s in taken} == {"c1", "c2"}
    # Returned in rank order regardless of the packing order used internally.
    assert [s["candidate_id"] for s in taken] == ["c1", "c2"]


def test_select_develop_relaxation_cant_manufacture_missing_candidates() -> None:
    # Only 2 develop candidates exist at all for 3 slots -- no relaxation
    # stage can conjure a 3rd, so assign_slots must still raise.
    slots = _slots(3)
    hook_id, close_id = "hook0", "close0"
    candidates_by_id = {
        hook_id: _candidate(hook_id, "hook.mov", "peak", 1.0, (0.0, 5.0)),
        close_id: _candidate(close_id, "close.mov", "calm", 5.0, (3.0, 8.0)),
        "c1": _candidate("c1", "a.mov", "peak", 2.0, (0.0, 4.0)),
        "c2": _candidate("c2", "b.mov", "peak", 2.0, (0.0, 4.0)),
    }
    selected = [
        _selected(hook_id, "hook", 1, exercise="hook_move"),
        _selected(close_id, "close", 1, exercise="close_move"),
        _selected("c1", "develop", 1, exercise="squat"),
        _selected("c2", "develop", 2, exercise="deadlift"),
    ]

    with pytest.raises(PlannerError, match="not enough develop candidates"):
        assign_slots(slots, selected, candidates_by_id)


def test_effect_for_hook_text_params() -> None:
    from edl_agent.planner import DEFAULT_CONFIG
    from edl_agent.planner.effects import effect_for

    cand = {"kind": "peak"}
    effect, params = effect_for(
        cand, "crop", DEFAULT_CONFIG, None, ("Sube el peso", 45)
    )
    assert effect == "none"
    assert params["text"] == "SUBE EL\\NPESO"  # upper-cased, wraps at full size
    assert params["font_size"] == DEFAULT_CONFIG["hook_text_size"]
    assert params["text_frames"] == 45

    # A line that doesn't fit one line and needs shrinking to wrap to two.
    _, params = effect_for(
        cand, "crop", DEFAULT_CONFIG, None, ("Último rep, sin excusas", 45)
    )
    assert params["text"] == "ÚLTIMO REP,\\NSIN EXCUSAS"
    assert 56 <= params["font_size"] < DEFAULT_CONFIG["hook_text_size"]
    assert params["fade_frames"] == DEFAULT_CONFIG["hook_text_fade_frames"]

    # A line that still doesn't fit as two lines shrinks below full size.
    _, params = effect_for(
        cand,
        "crop",
        DEFAULT_CONFIG,
        None,
        ("Supercalifragilisticoespialidoso total", 45),
    )
    assert "\\N" in params["text"]
    assert 56 <= params["font_size"] < DEFAULT_CONFIG["hook_text_size"]

    _, params = effect_for(cand, "crop", DEFAULT_CONFIG, None, ("", 45))
    assert "text" not in params
    _, params = effect_for(
        cand, "crop", {**DEFAULT_CONFIG, "hook_text": False}, None, ("x", 45)
    )
    assert "text" not in params


def test_effect_for_cut_fx() -> None:
    from edl_agent.planner import DEFAULT_CONFIG
    from edl_agent.planner.effects import effect_for

    cand = {"kind": "peak"}
    _, params = effect_for(cand, "crop", DEFAULT_CONFIG, role="develop", peak_f=15)
    assert "punch_frames" not in params
    assert "flash_frame" not in params

    _, params = effect_for(
        cand, "crop", {**DEFAULT_CONFIG, "punch_in": True}, role="develop", peak_f=15
    )
    assert params["punch_frames"] == DEFAULT_CONFIG["punch_frames"]
    assert params["punch_zoom"] == DEFAULT_CONFIG["punch_zoom"]

    _, params = effect_for(cand, "crop", DEFAULT_CONFIG, role="hook", peak_f=15)
    assert params["flash_frame"] == 15
    assert params["flash_frames"] == DEFAULT_CONFIG["flash_frames"]
    assert "punch_frames" not in params

    _, params = effect_for(cand, "crop", DEFAULT_CONFIG, role="close", peak_f=None)
    assert "punch_frames" not in params
    assert "flash_frame" not in params

    _, params = effect_for(
        cand, "crop", {**DEFAULT_CONFIG, "punch_in": False}, role="develop", peak_f=15
    )
    assert "punch_frames" not in params
    _, params = effect_for(
        cand, "crop", {**DEFAULT_CONFIG, "hook_flash": False}, role="hook", peak_f=15
    )
    assert "flash_frame" not in params

    img_cand = {"kind": "image"}
    effect, params = effect_for(
        img_cand, "crop", DEFAULT_CONFIG, role="develop", peak_f=None
    )
    assert effect == "kenburns"
    assert "punch_frames" not in params
