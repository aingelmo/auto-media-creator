"""Content-addressed cache reuse for run_candidates (#1 caching extension)."""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING

from edl_agent.session import run_candidates

if TYPE_CHECKING:
    from pathlib import Path


def _make_clip(path: Path, duration: int = 2) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "life=size=320x240:rate=30:ratio=0.5:mold=2:death_color=#000000",
            "-t",
            str(duration),
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def _manifest(session_dir: Path, sha256: str, duration_s: float) -> dict:
    return {
        "session_id": session_dir.name,
        "sources": [
            {
                "src": "inputs/a.mp4",
                "sha256": sha256,
                "type": "video",
                "proxy": "proxies/a.mp4",
                "duration_s": duration_s,
            }
        ],
    }


def test_run_candidates_reuses_cache_across_sessions(tmp_path, monkeypatch) -> None:
    import edl_agent.session.candidates as candidates_module

    cache_root = tmp_path / "cache"
    calls = {"extract_features": 0}
    real_extract_features = candidates_module.extract_features

    def counting_extract_features(*args: object, **kwargs: object):
        calls["extract_features"] += 1
        return real_extract_features(*args, **kwargs)

    monkeypatch.setattr(
        candidates_module, "extract_features", counting_extract_features
    )

    def fake_detector(frame):
        return []

    slots = {"slots": []}
    sha256 = "deadbeef" * 8

    session1 = tmp_path / "sess1"
    (session1 / "proxies").mkdir(parents=True)
    _make_clip(session1 / "proxies" / "a.mp4")
    manifest1 = _manifest(session1, sha256, duration_s=2.0)
    run_candidates(session1, manifest1, slots, fake_detector, cache_root=cache_root)
    assert calls["extract_features"] == 1

    session2 = tmp_path / "sess2"
    (session2 / "proxies").mkdir(parents=True)
    _make_clip(session2 / "proxies" / "a.mp4")
    manifest2 = _manifest(session2, sha256, duration_s=2.0)
    result2 = run_candidates(
        session2, manifest2, slots, fake_detector, cache_root=cache_root
    )
    assert calls["extract_features"] == 1
    assert result2["features_config_sha256"]

    feat_path2 = session2 / "features" / "a.parquet"
    assert feat_path2.is_symlink()
    cuts_path = cache_root / sha256 / "scene_cuts.json"
    assert json.loads(cuts_path.read_text()) == []
