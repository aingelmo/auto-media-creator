"""Music candidate generation propagates score breakdown fields."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch


def test_generate_music_candidates_keeps_breakdown(tmp_path) -> None:
    from edl_agent.web.stages import music as music_stage

    session_dir = tmp_path
    out_dir = session_dir / "music" / "candidates"
    track = session_dir / "music" / "track.mp3"
    track.parent.mkdir(parents=True)
    track.write_bytes(b"x")

    ranked = [
        {
            "offset_s": 33.7,
            "duration_s": 13.5,
            "end_s": 47.2,
            "score": 0.824,
            "reason": "energy jump (drop)",
            "d_close_beat_s": 0.0,
            "close_closure": 1.23,
        }
    ]

    def fake_cut(src, dst, offset, duration):
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        Path(dst).write_bytes(b"wav")
        return Path(dst)

    with (
        patch.object(music_stage, "rank_highlights", return_value=ranked),
        patch.object(music_stage, "cut_music", side_effect=fake_cut),
    ):
        results = music_stage._generate_music_candidates(
            track, out_dir, session_dir, 0, 167.0, None, count=1
        )

    assert len(results) == 1
    cand = results[0]
    assert cand["offset_s"] == 33.7
    assert cand["score"] == 0.824
    assert cand["reason"] == "energy jump (drop)"
    assert cand["close_closure"] == 1.23
    assert cand["d_close_beat_s"] == 0.0
