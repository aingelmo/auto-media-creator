"""Cierre de la Sesion 1 (#14): ingesta + proxy + verificacion temporal.

Clips sinteticos con ffmpeg lavfi cubriendo rotacion, HLG, start_time != 0,
60fps y 25fps. DV 8.4 no se puede fabricar con ffmpeg puro (requiere RPU real
Dolby Vision): se prueba solo la logica de clasificacion con un stream
ffprobe fabricado a mano.
"""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING

import pytest

from edl_agent.ingest import (
    IngestError,
    _video_stream,
    build_proxy,
    classify_hdr,
    ffprobe,
    post_rotation_dims,
    probe_video_source,
)
from edl_agent.session import run_ingest
from edl_agent.verify import (
    D0_MAX,
    _frame_seek_time,
    _instant_ok,
    pick_instants,
    verify_source,
)

if TYPE_CHECKING:
    from pathlib import Path


def _make_clip(path: Path, *, w=1080, h=1920, fps=30, duration=3, hlg=False) -> None:
    # `life` (Conway's game of life) gives genuine, chaotic frame-to-frame content
    # change. testsrc2's motion is smooth/continuous, and after resize+re-encode
    # its pHash distance between the *correct* proxy frame and its immediate
    # neighbours (+-1/30s) collapses into the same noise band as D0_MAX=6 - not
    # because the threshold is wrong, but because #4.4 is designed around motion
    # *peaks* (kp_speed maxima), which look like abrupt content changes, not
    # smooth drift. Verified empirically: on testsrc2, d_0 vs d_-1/d_1 differ by
    # a few bits at some instants; on `life`, the gap is consistently 10-20 bits.
    vf = f"life=size={w}x{h}:rate={fps}:ratio=0.5:mold=2:death_color=#000000"
    color_args = (
        [
            "-color_primaries",
            "bt2020",
            "-color_trc",
            "arib-std-b67",
            "-colorspace",
            "bt2020nc",
            "-pix_fmt",
            "yuv420p10le",
        ]
        if hlg
        else ["-pix_fmt", "yuv420p"]
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        vf,
        "-t",
        str(duration),
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        *color_args,
        str(path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def _make_offset_clip(
    path: Path, *, w=640, h=360, fps=30, duration=3, offset_s=1.5
) -> None:
    """Fabrica start_time != 0 igual que #14 paso 1: -itsoffset + -c copy."""
    tmp = path.with_suffix(".src.mp4")
    _make_clip(tmp, w=w, h=h, fps=fps, duration=duration)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-itsoffset",
            str(offset_s),
            "-i",
            str(tmp),
            "-c",
            "copy",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def session_dir(tmp_path: Path) -> Path:
    d = tmp_path / "sess"
    (d / "inputs").mkdir(parents=True)
    (d / "proxies").mkdir()
    return d


def test_post_rotation_dims_swaps_for_90_270() -> None:
    assert post_rotation_dims(1920, 1080, 90) == (1080, 1920)
    assert post_rotation_dims(1920, 1080, 270) == (1080, 1920)
    assert post_rotation_dims(1920, 1080, 0) == (1920, 1080)
    assert post_rotation_dims(1920, 1080, 180) == (1920, 1080)


def test_rotation_read_from_display_matrix_side_data() -> None:
    from edl_agent.ingest import _rotation

    stream = {"side_data_list": [{"side_data_type": "Display Matrix", "rotation": -90}]}
    assert _rotation(stream) == -90


def test_hlg_classified_and_proxy_verifies(session_dir) -> None:
    from edl_agent.ingest import TONEMAP_CHAIN_HLG

    clip = session_dir / "inputs" / "hlg.mp4"
    _make_clip(clip, w=1280, h=720, hlg=True, duration=2)
    info = probe_video_source(clip)
    assert info.hdr == "hlg"

    proxy = session_dir / "proxies" / "hlg.mp4"
    build_proxy(info, proxy)
    ok, results = verify_source(str(clip), str(proxy), tonemap_chain=TONEMAP_CHAIN_HLG)
    assert ok, results


def test_start_time_offset_does_not_break_verification(session_dir) -> None:
    clip = session_dir / "inputs" / "offset.mp4"
    _make_offset_clip(clip, w=640, h=360, duration=3, offset_s=1.5)
    info = probe_video_source(clip)
    assert info.start_time_s == pytest.approx(1.5, abs=0.05)

    proxy = session_dir / "proxies" / "offset.mp4"
    build_proxy(info, proxy)
    # percentile fallback (no kp_speed yet): exercises that in_s (relative to
    # -ss on the file, per #1) is not corrupted by start_time_s / -itsoffset.
    ok, results = verify_source(str(clip), str(proxy), tonemap_chain="")
    assert ok, results


# Real footage (A001_08231329_C001.mov, HEVC) showed verify_source falsely
# rejecting the near-start instant: libx264's default B-frames force
# -avoid_negative_ts to shift the whole proxy timeline forward by the
# reorder delay (~2 frames), so the proxy's video pts started at ~0.066s
# instead of 0 and every early comparison landed 2 frames off. See #4.4.
def test_proxy_video_pts_starts_at_zero(session_dir) -> None:
    clip = session_dir / "inputs" / "a.mp4"
    _make_clip(clip, w=640, h=360, duration=2)
    info = probe_video_source(clip)

    proxy = session_dir / "proxies" / "a.mp4"
    build_proxy(info, proxy)
    start_time = float(_video_stream(ffprobe(proxy))["start_time"])
    assert start_time == pytest.approx(0.0, abs=1e-3)


@pytest.mark.parametrize("fps", [60, 25])
def test_fps_variants_verify(session_dir, fps) -> None:
    clip = session_dir / "inputs" / f"fps{fps}.mp4"
    _make_clip(clip, w=640, h=360, fps=fps, duration=2)
    info = probe_video_source(clip)
    assert info.src_fps_nominal == fps

    proxy = session_dir / "proxies" / f"fps{fps}.mp4"
    build_proxy(info, proxy)
    ok, results = verify_source(str(clip), str(proxy), tonemap_chain="")
    assert ok, results


def test_dv84_classified_like_hlg_via_side_data() -> None:
    stream = {
        "pix_fmt": "yuv420p10le",
        "color_transfer": "arib-std-b67",
        "side_data_list": [{"side_data_type": "DOVI configuration record"}],
    }
    assert classify_hdr(stream) == "dv84"


def test_10bit_without_color_transfer_is_ingest_error() -> None:
    stream = {"pix_fmt": "yuv420p10le", "color_transfer": None, "side_data_list": []}
    with pytest.raises(IngestError):
        classify_hdr(stream)


def test_pick_instants_fills_with_percentiles_when_no_kp_speed() -> None:
    instants = pick_instants(duration_s=20.0, extra_instants_s=None)
    assert instants == [2.0, 10.0, 18.0]


def test_pick_instants_prioritises_extra_up_to_five() -> None:
    instants = pick_instants(
        duration_s=20.0, extra_instants_s=[1.0, 3.0, 5.0, 7.0, 9.0]
    )
    assert instants == [1.0, 3.0, 5.0, 7.0, 9.0]


# Real sessions (real_test_01) showed the old exact-argmin check rejecting
# ~67% of genuinely aligned clips: on static/slow-motion content, pHash noise
# (worsened by HDR tonemap) routinely makes a +-1/+-2 frame neighbour score a
# few bits below d0 with no real content shift. See docs #4.4 riesgo #13.
def test_instant_ok_tolerates_neighbour_within_margin() -> None:
    # d0 within D0_MAX but not the exact argmin (real failures observed: diff of 2-4).
    assert _instant_ok({-2: 2, -1: 2, 0: 2, 1: 2, 2: 0})


def test_instant_ok_rejects_when_gap_to_best_too_large() -> None:
    # d0 itself is within D0_MAX, but a neighbour is drastically better: genuine shift.
    assert not _instant_ok({-2: 6, -1: 6, 0: 6, 1: 0, 2: 0})


def test_instant_ok_rejects_when_d0_exceeds_threshold() -> None:
    assert not _instant_ok({-2: 0, -1: 0, 0: D0_MAX + 1, 1: 0, 2: 0})


# ffmpeg's `-ss` seeks to the first frame with pts >= the requested time
# (ceiling), not the nearest one. On real HEVC footage this made
# verify_source compare against the *next* frame instead of the intended
# one whenever an instant fell just past a frame boundary (#4.4).
def test_frame_seek_time_snaps_to_nearest_frame_not_next() -> None:
    # t sits between frame 439 (pts=14.6333) and 440 (pts=14.6667), closer
    # to 439 - a raw `-ss t` would ceiling-seek to 440 instead.
    t = 14.640000300000002
    assert _frame_seek_time(t, fps=30) == pytest.approx(439 / 30, abs=1e-3)


def test_run_ingest_end_to_end(session_dir) -> None:
    _make_clip(session_dir / "inputs" / "a.mp4", w=640, h=360, duration=2)
    manifest = run_ingest(session_dir, threads=2)

    assert manifest["session_id"] == session_dir.name
    assert len(manifest["sources"]) == 1
    src = manifest["sources"][0]
    assert src["proxy_verified"] is True
    assert src["has_audio"] is False
    assert (session_dir / "manifest.json").exists()


def test_run_ingest_reuses_cache_across_sessions(tmp_path, monkeypatch) -> None:
    import edl_agent.session.ingest as ingest_module

    cache_root = tmp_path / "cache"
    calls = {"build_proxy": 0, "verify_source": 0}
    real_build_proxy = ingest_module.build_proxy
    real_verify_source = ingest_module.verify_source

    def counting_build_proxy(*args: object, **kwargs: object):
        calls["build_proxy"] += 1
        return real_build_proxy(*args, **kwargs)

    def counting_verify_source(*args: object, **kwargs: object):
        calls["verify_source"] += 1
        return real_verify_source(*args, **kwargs)

    monkeypatch.setattr(ingest_module, "build_proxy", counting_build_proxy)
    monkeypatch.setattr(ingest_module, "verify_source", counting_verify_source)

    import shutil

    clip = tmp_path / "a.mp4"
    _make_clip(clip, w=640, h=360, duration=2)

    def make_session(name: str) -> Path:
        d = tmp_path / name
        (d / "inputs").mkdir(parents=True)
        shutil.copy(clip, d / "inputs" / "a.mp4")
        return d

    session1 = make_session("sess1")
    run_ingest(session1, threads=2, cache_root=cache_root)
    assert calls == {"build_proxy": 1, "verify_source": 1}

    session2 = make_session("sess2")
    manifest2 = run_ingest(session2, threads=2, cache_root=cache_root)
    assert calls == {"build_proxy": 1, "verify_source": 1}
    assert manifest2["sources"][0]["proxy_verified"] is True

    proxy2 = session2 / "proxies" / "a.mp4"
    assert proxy2.is_symlink()
    cached_sha = manifest2["sources"][0]["sha256"]
    assert proxy2.resolve() == cache_root / cached_sha / "proxy.mp4"


def _race_writer(target: Path, payload: str) -> None:
    from edl_agent.ingest.cache import atomic_write_text

    for _ in range(30):
        atomic_write_text(target, payload)


def test_atomic_write_text_never_exposes_partial_file(tmp_path) -> None:
    """Two processes racing on the same cache path (#concurrency): a
    concurrent reader only ever sees a complete file, never a torn one, and
    no leftover per-pid temp files remain once both writers finish."""
    import multiprocessing
    import threading

    from edl_agent.ingest.cache import atomic_write_text

    target = tmp_path / "sha" / "info.json"
    payload_a = json.dumps({"who": "a", "pad": "x" * 5000})
    payload_b = json.dumps({"who": "b", "pad": "y" * 5000})
    atomic_write_text(target, payload_a)  # ensure it exists before racing
    seen_partial = []
    stop = threading.Event()

    def reader() -> None:
        while not stop.is_set():
            try:
                data = json.loads(target.read_text())
            except (ValueError, OSError):
                seen_partial.append(True)
                continue
            if data["who"] not in ("a", "b"):
                seen_partial.append(True)

    reader_thread = threading.Thread(target=reader)
    reader_thread.start()
    ctx = multiprocessing.get_context("fork")
    p1 = ctx.Process(target=_race_writer, args=(target, payload_a))
    p2 = ctx.Process(target=_race_writer, args=(target, payload_b))
    p1.start()
    p2.start()
    p1.join()
    p2.join()
    stop.set()
    reader_thread.join()

    assert not seen_partial
    assert json.loads(target.read_text())["who"] in ("a", "b")
    assert not list(tmp_path.rglob("*.tmp.*"))
