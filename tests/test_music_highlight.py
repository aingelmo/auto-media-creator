"""#3.5 Rank music highlight windows by drop-detection heuristic."""

from __future__ import annotations

import math
import wave

import pytest

from edl_agent.ingest.highlight import rank_highlights

SR = 22050


def _synth_track(path) -> None:
    """20s quiet, 15s loud four-on-the-floor, 20s quiet, at `SR` Hz."""
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        for t_start, dur, amp, click_hz in (
            (0.0, 20.0, 0.02, 1.0),
            (20.0, 15.0, 0.9, 2.0),
            (35.0, 20.0, 0.02, 1.0),
        ):
            n = round(dur * SR)
            samples = bytearray()
            for i in range(n):
                t = t_start + i / SR
                # four-on-the-floor: short click bursts at click_hz
                phase = (t * click_hz) % 1.0
                env = 1.0 if phase < 0.1 else 0.0
                val = amp * env * math.sin(2 * math.pi * 220 * t)
                samples += int(max(-1.0, min(1.0, val)) * 32767).to_bytes(
                    2, "little", signed=True
                )
            w.writeframes(bytes(samples))


def test_top_ranked_offset_lands_in_loud_region(tmp_path) -> None:
    track = tmp_path / "track.wav"
    _synth_track(track)

    ranked = rank_highlights(track, window_s=15.0)

    assert ranked
    top = ranked[0]
    assert 18.0 <= top["offset_s"] <= 35.0
    assert 0.0 <= top["score"] <= 1.0


def test_fixed_window_reports_close_diagnostics(tmp_path) -> None:
    track = tmp_path / "track.wav"
    _synth_track(track)

    ranked = rank_highlights(track, window_s=15.0)

    assert ranked
    for cand in ranked[:3]:
        assert cand["duration_s"] == pytest.approx(15.0, abs=0.02)
        assert cand["end_s"] == pytest.approx(cand["offset_s"] + 15.0, abs=0.02)
        assert cand["close_closure"] >= 0.0
        assert 0.0 <= cand["score"] <= 1.0
        d_close = cand["d_close_beat_s"]
        assert d_close is None or d_close >= 0.0


def test_joint_window_selects_duration_on_beats(tmp_path) -> None:
    track = tmp_path / "track.wav"
    _synth_track(track)

    ranked = rank_highlights(track, window_s=15.0, min_window_s=8.0)

    assert ranked
    pairs = set()
    for cand in ranked:
        assert 8.0 <= cand["duration_s"] <= 15.0
        assert cand["end_s"] == pytest.approx(
            cand["offset_s"] + cand["duration_s"], abs=0.02
        )
        assert cand["close_closure"] >= 0.0
        assert 0.0 <= cand["score"] <= 1.0
        pairs.add((cand["offset_s"], cand["end_s"]))
    # Post-snap collisions share one clip: the ranking must not list the
    # same (offset, end) twice.
    assert len(pairs) == len(ranked)


def test_ranking_is_cached(tmp_path) -> None:
    track = tmp_path / "track.wav"
    _synth_track(track)
    cache_root = tmp_path / "cache"
    cache_root.mkdir()

    first = rank_highlights(track, window_s=15.0, cache_root=cache_root)
    sha_dirs = list(cache_root.iterdir())
    assert len(sha_dirs) == 1
    assert (sha_dirs[0] / "music_highlights.json").exists()

    second = rank_highlights(track, window_s=15.0, cache_root=cache_root)
    assert second == first


def test_short_track_falls_back_to_full_range(tmp_path) -> None:
    track = tmp_path / "short.wav"
    with wave.open(str(track), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        n = round(2.0 * SR)
        w.writeframes(
            b"".join(
                int(0.1 * 32767 * math.sin(2 * math.pi * 220 * i / SR)).to_bytes(
                    2, "little", signed=True
                )
                for i in range(n)
            )
        )

    ranked = rank_highlights(track, window_s=1.0)
    assert ranked
