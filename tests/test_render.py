"""Cierre del paso 2 de #14: render + concat + audio desde una EDL escrita a
mano (#10), sin CV ni LLM. Hook a speed=0.5 sobre fuente 60 fps (slow-motion
real) y clip a speed=1.0 sobre fuente 30 fps.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from edl_agent.ingest import build_proxy, probe_video_source, sha256_file
from edl_agent.render import crop_to_px, is_916, run_render


def _make_clip(path: Path, *, w=360, h=640, fps=30, duration=3):
    vf = f"life=size={w}x{h}:rate={fps}:ratio=0.5:mold=2:death_color=#000000"
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi", "-i", vf, "-t", str(duration),
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def _make_sine(path: Path, duration=4):
    # afade envelope gives a non-zero LRA; a flat tone sits on the knife-edge
    # of ffmpeg's linear/dynamic loudnorm decision and flips unpredictably.
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
        "-af", f"afade=t=in:d=0.5,afade=t=out:st={duration - 0.5}:d=0.5,volume=0.7",
        "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def _clip(slot, role, src, src_w, src_h, in_s, out_s, n_frames, speed, timeline_start, timeline_end):
    crop_px = {"x": 0, "y": 0, "w": src_w, "h": src_h}
    return {
        "slot": slot, "role": role, "candidate_id": f"c{slot}",
        "src": src, "src_sha256": "x", "type": "video",
        "src_w": src_w, "src_h": src_h, "src_rotation": 0,
        "src_color": {"primaries": "bt709", "trc": "bt709", "space": "bt709", "range": "tv"},
        "hdr": "none",
        "in_s": in_s, "out_s": out_s, "n_frames": n_frames, "speed": speed,
        "timeline_start_f": timeline_start, "timeline_end_f": timeline_end,
        "layout": "crop", "crop": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}, "crop_px": crop_px,
        "effect": "none", "effect_params": {}, "warnings": [],
    }


@pytest.fixture
def session_dir(tmp_path: Path) -> Path:
    d = tmp_path / "sess"
    (d / "inputs").mkdir(parents=True)
    (d / "proxies").mkdir()
    return d


def test_crop_to_px_identity_for_916_source():
    assert crop_to_px({"x": 0, "y": 0, "w": 1, "h": 1}, 1080, 1920, "crop") == {
        "x": 0, "y": 0, "w": 1080, "h": 1920,
    }


def test_is_916():
    assert is_916(1080, 1920)
    assert not is_916(1920, 1080)


def test_render_e2e_hook_slowmo_and_deterministic_rerender(session_dir):
    clip_a = session_dir / "inputs" / "a.mp4"  # hook: 60 fps, speed 0.5
    _make_clip(clip_a, w=360, h=640, fps=60, duration=3)
    clip_b = session_dir / "inputs" / "b.mp4"  # close: 30 fps, speed 1.0
    _make_clip(clip_b, w=360, h=640, fps=30, duration=3)

    info_a = probe_video_source(clip_a)
    build_proxy(info_a, session_dir / "proxies" / "a.mp4")
    info_b = probe_video_source(clip_b)
    build_proxy(info_b, session_dir / "proxies" / "b.mp4")

    _make_sine(session_dir / "music" / "track_cut.wav", duration=4)

    manifest = {
        "session_id": "sess",
        "target": {"w": 1080, "h": 1920, "fps": 30},
        "sources": [
            {"src": "inputs/a.mp4", "sha256": info_a.sha256, "type": "video", "proxy": "proxies/a.mp4"},
            {"src": "inputs/b.mp4", "sha256": info_b.sha256, "type": "video", "proxy": "proxies/b.mp4"},
        ],
    }

    edl = {
        "version": 4, "session_id": "sess",
        "target": {"w": 1080, "h": 1920, "fps": 30, "duration_f": 90},
        "clips": [
            _clip(0, "hook", "inputs/a.mp4", 360, 640, 0.0, 0.75, 45, 0.5, 0, 45),
            _clip(1, "close", "inputs/b.mp4", 360, 640, 0.5, 2.0, 45, 1.0, 45, 90),
        ],
        "audio": {
            "music_cut_path": "music/track_cut.wav", "music_cut_sha256": None,
            "music_src_path": None, "music_src_sha256": None,
            "music_offset_s": 0.0, "target_lufs": -14.0, "target_tp": -1.0, "target_lra": 11.0,
            "loudnorm_measured": None, "loudnorm_applied": None, "fade_out_s": 0.3,
        },
    }

    results = run_render(edl, manifest, session_dir, threads=2)
    assert all(r.ok for r in results), [r for r in results if not r.ok]
    assert edl["audio"]["loudnorm_applied"]["normalization_type"] == "linear"

    reel = session_dir / "reel.mp4"
    sha1 = sha256_file(reel)

    edl_rerun = json.loads(json.dumps(edl))
    run_render(edl_rerun, manifest, session_dir, threads=2)
    assert sha256_file(reel) == sha1
