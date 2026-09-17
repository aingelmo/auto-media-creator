"""#4.3 peak-window NMS and pHash dedup."""

from __future__ import annotations

import numpy as np
from PIL import Image

from edl_agent.candidates.dedup import dedup_windows_by_phash, suppress_peak_windows


def test_suppress_peak_windows_keeps_highest_kp_speed_abs_on_overlap() -> None:
    features = {"kp_speed_abs": [0.0] * 10}
    features["kp_speed_abs"][1] = 2.0  # second window scores higher
    windows = [
        {"kind": "peak", "t_peak": 1.0, "window": [0.5, 1.5], "index": 0},
        {"kind": "peak", "t_peak": 1.1, "window": [0.6, 1.6], "index": 1},
    ]

    kept = suppress_peak_windows(windows, features)

    assert len(kept) == 1
    assert kept[0]["index"] == 1


def test_suppress_peak_windows_caps_per_clip() -> None:
    features = {"kp_speed_abs": [1.0, 2.0, 3.0, 4.0]}
    # windows spaced far enough apart that NMS alone wouldn't drop any
    windows = [
        {"kind": "peak", "t_peak": t, "window": [t - 0.1, t + 0.1], "index": i}
        for i, t in enumerate([1.0, 10.0, 20.0, 30.0])
    ]

    kept = suppress_peak_windows(windows, features)

    assert len(kept) == 3  # PEAK_MAX_PER_CLIP


def test_dedup_windows_by_phash_drops_visual_duplicate(monkeypatch) -> None:
    # phash is invariant to flat color (DCT of a constant frame is all-zero),
    # so use distinct noise patterns: same seed = "near-duplicate" frame,
    # different seed = genuinely different content.
    seeds = {0.0: 1, 0.1: 1, 9.0: 2}

    def fake_probe(proxy_path, t, out_path) -> None:
        arr = np.random.default_rng(seeds[t]).integers(
            0, 256, (96, 128, 3), dtype=np.uint8
        )
        Image.fromarray(arr).save(out_path)

    monkeypatch.setattr("edl_agent.candidates.dedup._probe_frame", fake_probe)

    windows = [
        {"kind": "peak", "t_peak": 0.0, "window": [0.0, 1.0]},
        {"kind": "peak", "t_peak": 0.1, "window": [0.1, 1.1]},  # near-dup of the above
        {"kind": "peak", "t_peak": 9.0, "window": [9.0, 10.0]},
    ]

    kept = dedup_windows_by_phash(windows, "unused.mp4")

    assert [w["t_peak"] for w in kept] == [0.0, 9.0]
