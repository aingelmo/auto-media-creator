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
    build_clips,
    compute_in_out,
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

    hook_id = "hook0"
    sources_by_src["hook.mov"] = _source("hook.mov", w, h)
    candidates_by_id[hook_id] = _candidate(
        hook_id, "hook.mov", "peak", t_peak=1.0, window=(0.0, 5.0)
    )
    selected.append(_selected(hook_id, "hook", 1))

    close_id = "close0"
    sources_by_src["close.mov"] = _source("close.mov", w, h)
    candidates_by_id[close_id] = _candidate(
        close_id, "close.mov", "calm", t_peak=5.0, window=(3.0, 8.0)
    )
    selected.append(_selected(close_id, "close", 1))

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


@pytest.mark.parametrize(("aspect_name", "w", "h"), ASPECTS)
@pytest.mark.parametrize("n_develop", [1, 2, 4, 5, 6])
def test_planner_invariants(aspect_name, w, h, n_develop) -> None:
    slots, selected, candidates_by_id, sources_by_src = _build_scenario(
        n_develop, (w, h), seed=n_develop * 7
    )
    clips, warnings = build_clips(slots, selected, candidates_by_id, sources_by_src)

    n_slots = n_develop + 2
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
            # P5
            assert round((c["out_s"] - c["in_s"]) / c["speed"] * FPS) == c["n_frames"]
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
        cand, slot, role="develop", speed=1.0, config=DEFAULT_CONFIG
    )

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
        cand, slot, role="develop", speed=1.0, config=DEFAULT_CONFIG
    )
    assert timing["in_s"] == 0.0
    assert "peak_off_beat" in timing["warnings"]


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
