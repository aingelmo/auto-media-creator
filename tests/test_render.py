"""Cierre del paso 2 de #14: render + concat + audio desde una EDL escrita a
mano (#10), sin CV ni LLM. Hook con speed ramp (0.4x en 12 frames) sobre fuente
60 fps (slow-motion real) y clip a 1.0x sobre fuente 30 fps.
"""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING, Any

import pytest
from PIL import Image

from edl_agent.ingest import build_proxy, probe_video_source, sha256_file
from edl_agent.planner._common import DEFAULT_CONFIG
from edl_agent.render import crop_to_px, is_916, render_segments, run_render

if TYPE_CHECKING:
    from pathlib import Path

_DEJAVU_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def _make_clip(path: Path, *, w=360, h=640, fps=30, duration=3, audio=False) -> None:
    vf = f"life=size={w}x{h}:rate={fps}:ratio=0.5:mold=2:death_color=#000000:seed=42"
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", vf]
    if audio:
        cmd += ["-f", "lavfi", "-i", "sine=frequency=1000"]
    cmd += [
        "-t",
        str(duration),
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
    ]
    if audio:
        cmd += ["-c:a", "aac", "-shortest"]
    cmd.append(str(path))
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def _make_sine(path: Path, duration=4) -> None:
    # afade envelope gives a non-zero LRA; a flat tone sits on the knife-edge
    # of ffmpeg's linear/dynamic loudnorm decision and flips unpredictably.
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=440:duration={duration}",
        "-af",
        f"afade=t=in:d=0.5,afade=t=out:st={duration - 0.5}:d=0.5,volume=0.7",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-c:a",
        "pcm_s16le",
        str(path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def _clip(
    slot,
    role,
    src,
    src_w,
    src_h,
    in_s,
    out_s,
    n_frames,
    speed,
    timeline_start,
    timeline_end,
):
    crop_px = {"x": 0, "y": 0, "w": src_w, "h": src_h}
    return {
        "slot": slot,
        "role": role,
        "candidate_id": f"c{slot}",
        "src": src,
        "src_sha256": "x",
        "type": "video",
        "src_w": src_w,
        "src_h": src_h,
        "src_rotation": 0,
        "src_color": {
            "primaries": "bt709",
            "trc": "bt709",
            "space": "bt709",
            "range": "tv",
        },
        "hdr": "none",
        "in_s": in_s,
        "out_s": out_s,
        "n_frames": n_frames,
        "speed": speed,
        "timeline_start_f": timeline_start,
        "timeline_end_f": timeline_end,
        "layout": "crop",
        "crop": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0},
        "crop_px": crop_px,
        "effect": "none",
        "effect_params": {},
        "warnings": [],
    }


@pytest.fixture
def session_dir(tmp_path: Path) -> Path:
    d = tmp_path / "sess"
    (d / "inputs").mkdir(parents=True)
    (d / "proxies").mkdir()
    return d


def test_crop_to_px_identity_for_916_source() -> None:
    assert crop_to_px({"x": 0, "y": 0, "w": 1, "h": 1}, 1080, 1920, "crop") == {
        "x": 0,
        "y": 0,
        "w": 1080,
        "h": 1920,
    }


def test_is_916() -> None:
    assert is_916(1080, 1920)
    assert not is_916(1920, 1080)


def test_render_e2e_hook_slowmo_and_deterministic_rerender(session_dir) -> None:
    clip_a = session_dir / "inputs" / "a.mp4"  # hook: 60 fps, ramp 0.4x
    _make_clip(clip_a, w=360, h=640, fps=60, duration=3, audio=True)
    clip_b = session_dir / "inputs" / "b.mp4"  # close: 30 fps, speed 1.0
    _make_clip(clip_b, w=360, h=640, fps=30, duration=3)

    info_a = probe_video_source(clip_a)
    build_proxy(info_a, session_dir / "proxies" / "a.mp4")
    info_b = probe_video_source(clip_b)
    build_proxy(info_b, session_dir / "proxies" / "b.mp4")

    _make_sine(session_dir / "music" / "track_cut.wav", duration=4)

    (session_dir / "brand").mkdir()
    logo = Image.new("RGBA", (200, 80), (255, 0, 0, 255))
    logo.save(session_dir / "brand" / "logo.png")

    manifest = {
        "session_id": "sess",
        "target": {"w": 1080, "h": 1920, "fps": 30},
        "sources": [
            {
                "src": "inputs/a.mp4",
                "sha256": info_a.sha256,
                "type": "video",
                "proxy": "proxies/a.mp4",
            },
            {
                "src": "inputs/b.mp4",
                "sha256": info_b.sha256,
                "type": "video",
                "proxy": "proxies/b.mp4",
            },
        ],
    }

    edl: dict[str, Any] = {
        "version": 4,
        "session_id": "sess",
        "target": {"w": 1080, "h": 1920, "fps": 30, "duration_f": 75},
        "brand": {
            "logo": "brand/logo.png",
            "logo_sha256": "x",
            "logo_w": 200,
            "logo_h": 80,
            "watermark": {
                "w": 160,
                "opacity": 0.6,
                "inset_x": 48,
                "bottom_frac": 0.177,
            },
        },
        "clips": [
            {
                # 45 frames = 33 at 1.0x + 12 at 0.4x -> 1.1 + 0.16 = 1.26 s
                **_clip(0, "hook", "inputs/a.mp4", 360, 640, 0.0, 1.26, 45, 1.0, 0, 45),
                "effect": "ramp",
                "effect_params": {
                    "ramp_speed": 0.4,
                    "ramp_frames": 12,
                    "ramp_start_f": 9,
                    # hook text (#6.6) rides on top of the ramp
                    "text": "PRUEBA: 100% REAL",
                    "font": DEFAULT_CONFIG["hook_text_font"],
                    "font_size": 88,
                    "text_y": 0.40,
                    "text_frames": 45,
                    "fade_frames": 8,
                    # hook flash (#6.6) on the peak beat
                    "flash_frame": 9,
                    "flash_frames": 2,
                },
            },
            # close carries the C0 outro on its tail (24 of its 30 frames)
            {
                **_clip(
                    1, "close", "inputs/b.mp4", 360, 640, 0.5, 1.5, 30, 1.0, 45, 75
                ),
                # punch-in (#6.6), normally develop-only; exercised here
                # since this EDL is hand-written rather than planner-built
                "effect_params": {
                    "punch_frames": 5,
                    "punch_zoom": 1.06,
                    "outro_frames": 24,
                    "outro_fg": "#FFFFFF",
                    "outro_font": _DEJAVU_BOLD,
                    "outro_handle": "@gym",
                    "outro_logo_src": "brand/logo.png",
                    "outro_logo_w": 360,
                    "outro_logo_h": 144,
                    "outro_text_size": 64,
                    "outro_blur_radius": 20,
                    "outro_blur_power": 2,
                    "outro_dim": -0.3,
                },
            },
        ],
        "audio": {
            "music_cut_path": "music/track_cut.wav",
            "music_cut_sha256": None,
            "music_src_path": None,
            "music_src_sha256": None,
            "music_offset_s": 0.0,
            "target_lufs": -14.0,
            "target_tp": -1.0,
            "target_lra": 11.0,
            "loudnorm_measured": None,
            "loudnorm_applied": None,
            "fade_out_s": 0.3,
            "sfx": [
                {
                    "slot": 0,
                    "src": "inputs/a.mp4",
                    "in_s": 0.0,
                    "dur_s": 1.26,
                    "delay_ms": 0,
                    "gain_db": -18.0,
                    "ramp": {"start_f": 9, "frames": 12, "speed": 0.4},
                }
            ],
        },
    }

    results = run_render(edl, manifest, session_dir, threads=2)
    assert all(r.ok for r in results), [r for r in results if not r.ok]
    loudnorm_applied: Any = edl["audio"]["loudnorm_applied"]
    assert loudnorm_applied["normalization_type"] == "linear"

    reel = session_dir / "reel.mp4"
    sha1 = sha256_file(reel)

    edl_rerun = json.loads(json.dumps(edl))
    run_render(edl_rerun, manifest, session_dir, threads=2)
    assert sha256_file(reel) == sha1

    # sfx mix was actually applied: dropping it changes the reel's audio.
    edl_no_sfx = json.loads(json.dumps(edl))
    edl_no_sfx["audio"]["sfx"] = []
    run_render(edl_no_sfx, manifest, session_dir, threads=2)
    assert sha256_file(reel) != sha1

    # Watermark landed: the bottom-right logo box of the close's frame 0 is
    # red-tinted, and the end card's canvas is the brand bg.
    def _pixel(seg: str, x: int, y: int, frame: int = 0) -> Any:
        png = session_dir / f"{seg}.png"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(session_dir / "segments" / f"{seg}.mp4"),
                "-vf",
                f"select=eq(n\\,{frame})",
                "-frames:v",
                "1",
                str(png),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        with Image.open(png) as im:
            return im.convert("RGB").getpixel((x, y))

    r, g, b = _pixel("seg_01", 1080 - 48 - 80, 1920 - 340 - 32)
    assert r > g + 40 and r > b + 40
    # C0 outro: the close tail (last 24 of 30 frames) carries the red
    # logo centred (540, 860 falls inside the 360x144 overlay) once its
    # 0.25s alpha fade has completed (frame 25).
    r, g, b = _pixel("seg_01", 540, 860, frame=25)
    assert r > g + 40 and r > b + 40

    # Hook flash: frame 9 (peak beat) of seg_00 is white, decaying by frame 10.
    r, g, b = _pixel("seg_00", 180, 320, frame=9)
    assert min(r, g, b) > 230
    r10, g10, b10 = _pixel("seg_00", 180, 320, frame=10)
    assert sum((r10, g10, b10)) < sum((r, g, b))


def test_run_render_no_preview_skips_preview_segments(session_dir) -> None:
    """P0 light-device: `preview=False` renders the reel without the
    duplicate 540p preview encode."""
    clip_a = session_dir / "inputs" / "a.mp4"
    _make_clip(clip_a, w=360, h=640, fps=30, duration=2)
    info_a = probe_video_source(clip_a)
    build_proxy(info_a, session_dir / "proxies" / "a.mp4")
    _make_sine(session_dir / "music" / "track_cut.wav", duration=2)

    manifest = {
        "session_id": "sess",
        "target": {"w": 1080, "h": 1920, "fps": 30},
        "sources": [
            {"src": "inputs/a.mp4", "sha256": info_a.sha256, "type": "video"},
        ],
    }
    edl: dict[str, Any] = {
        "version": 4,
        "session_id": "sess",
        "target": {"w": 1080, "h": 1920, "fps": 30, "duration_f": 30},
        "brand": {},
        "clips": [
            _clip(0, "hook", "inputs/a.mp4", 360, 640, 0.0, 1.0, 30, 1.0, 0, 30),
        ],
        "audio": {
            "music_cut_path": "music/track_cut.wav",
            "music_cut_sha256": None,
            "music_src_path": None,
            "music_src_sha256": None,
            "music_offset_s": 0.0,
            "target_lufs": -14.0,
            "target_tp": -1.0,
            "target_lra": 11.0,
            "loudnorm_measured": None,
            "loudnorm_applied": None,
            "fade_out_s": 0.3,
            "sfx": [],
        },
    }

    results = run_render(edl, manifest, session_dir, threads=2, preview=False)
    assert all(r.ok for r in results), [r for r in results if not r.ok]
    assert (session_dir / "reel.mp4").exists()
    assert not (session_dir / "preview_segments").exists()


def test_render_segments_suffix_and_reuse(session_dir) -> None:
    """Variant-B segment reuse (idea #7): identical clips hardlink, changed
    ones re-render."""
    clip_a = session_dir / "inputs" / "a.mp4"
    _make_clip(clip_a, w=360, h=640, fps=30, duration=3)
    clip_b = session_dir / "inputs" / "b.mp4"
    _make_clip(clip_b, w=360, h=640, fps=30, duration=3)
    info_a = probe_video_source(clip_a)
    info_b = probe_video_source(clip_b)

    manifest = {
        "session_id": "sess",
        "target": {"w": 1080, "h": 1920, "fps": 30},
        "sources": [
            {"src": "inputs/a.mp4", "sha256": info_a.sha256, "type": "video"},
            {"src": "inputs/b.mp4", "sha256": info_b.sha256, "type": "video"},
        ],
    }
    clips_a = [
        _clip(0, "hook", "inputs/a.mp4", 360, 640, 0.0, 0.5, 15, 1.0, 0, 15),
        _clip(1, "close", "inputs/b.mp4", 360, 640, 0.5, 1.0, 15, 1.0, 15, 30),
    ]
    edl_a = {"clips": clips_a}
    render_segments(edl_a, manifest, session_dir, threads=2)

    # Variant B: slot 0 unchanged, slot 1's in/out shifted.
    clips_b = [
        clips_a[0],
        _clip(1, "close", "inputs/b.mp4", 360, 640, 1.0, 1.5, 15, 1.0, 15, 30),
    ]
    edl_b = {"clips": clips_b}
    clips_b_by_slot = {c["slot"]: c for c in clips_b}
    reuse = {
        c["slot"]: session_dir / "segments" / f"seg_{c['slot']:02d}.mp4"
        for c in clips_a
        if c == clips_b_by_slot.get(c["slot"])
    }
    assert set(reuse) == {0}

    render_segments(edl_b, manifest, session_dir, threads=2, suffix="_b", reuse=reuse)

    seg_dir_b = session_dir / "segments_b"
    assert seg_dir_b.is_dir()
    reused = seg_dir_b / "seg_00.mp4"
    rerendered = seg_dir_b / "seg_01.mp4"
    seg_00_a = session_dir / "segments" / "seg_00.mp4"
    seg_01_a = session_dir / "segments" / "seg_01.mp4"
    assert reused.stat().st_ino == seg_00_a.stat().st_ino
    assert reused.stat().st_nlink == 2
    assert rerendered.stat().st_ino != seg_01_a.stat().st_ino


def test_sfx_chain_ramp_vs_plain() -> None:
    from edl_agent.render.concat import _sfx_chain

    ramp_entry = {
        "gain_db": -18.0,
        "delay_ms": 100,
        "ramp": {"start_f": 9, "frames": 12, "speed": 0.4},
    }
    plain_entry = {"gain_db": -18.0, "delay_ms": 100, "ramp": None}

    ramp_chain = _sfx_chain(ramp_entry)
    assert "asetrate=48000*0.4" in ramp_chain
    assert "adelay=100:all=1" in ramp_chain
    assert "concat=" in ramp_chain

    assert "concat=" not in _sfx_chain(plain_entry)


def test_fade_completes_when_outro_starts() -> None:
    from edl_agent.render.concat import _fade_window, _outro_s

    edl = {"clips": [{"effect_params": {"outro_frames": 24}}]}
    assert _outro_s(edl) == pytest.approx(0.8)
    # 2.5s reel, 0.5s fade: ends at 1.7s == outro start, silent under logo.
    assert _fade_window(2.5, 0.5, _outro_s(edl)) == pytest.approx((1.2, 0.5))
    # No outro: unchanged behaviour, fade ends at the reel end.
    assert _fade_window(2.5, 0.5, 0.0) == pytest.approx((2.0, 0.5))
    # Reel shorter than outro+fade: clamped, never negative.
    assert _fade_window(0.5, 0.5, 0.8) == (0.0, 0.0)


def test_drawtext_escape_survives_both_ffmpeg_parsers() -> None:
    from edl_agent.render._common import _drawtext_escape

    assert _drawtext_escape("100% real: it's, a\\b") == (
        "100% real\\\\: it\\\\\\'s\\, a\\\\\\\\b"
    )
    assert _drawtext_escape("Sube el peso") == "Sube el peso"


def test_hook_text_filter_writes_ass_script(tmp_path) -> None:
    from edl_agent.planner._common import DEFAULT_CONFIG
    from edl_agent.render._common import hook_text_filter

    clip = {
        "effect_params": {
            "text": "ÚLTIMO REP,\\NSIN {EXCUSAS}",
            "font": DEFAULT_CONFIG["hook_text_font"],
            "font_size": 92,
            "text_y": 0.40,
            "text_frames": 45,  # 1.50s at 30fps
            "fade_frames": 6,
        }
    }
    out_path = tmp_path / "seg_00.mp4"

    filt = hook_text_filter(clip, out_path)

    ass_path = tmp_path / "seg_00.ass"
    assert ass_path.exists()
    content = ass_path.read_text()
    assert "PlayResX: 1080" in content
    assert "PlayResY: 1920" in content
    assert "Style: Hook,Montserrat," in content
    # Stray braces are stripped, not escaped -- they'd otherwise open a
    # second (bogus) ASS override block.
    assert "SIN EXCUSAS" in content
    assert "{EXCUSAS}" not in content
    assert "Dialogue: 0,0:00:00.00,0:00:01.50,Hook" in content
    assert r"\N" in content
    assert "filename=" in filt and "fontsdir=" in filt
    assert filt.endswith(",")


def test_hook_text_filter_empty_text_is_noop(tmp_path) -> None:
    from edl_agent.render._common import hook_text_filter

    assert hook_text_filter({"effect_params": {}}, tmp_path / "seg_00.mp4") == ""
    assert not (tmp_path / "seg_00.ass").exists()


def test_render_hook_previews_builds_one_variant_per_line_plus_none(
    session_dir, monkeypatch
) -> None:
    from edl_agent.planner._common import DEFAULT_CONFIG
    from edl_agent.render.hook_previews import render_hook_previews

    hook_clip = _clip(0, "hook", "inputs/a.mp4", 360, 640, 0.0, 1.0, 30, 1.0, 0, 30)
    hook_clip["effect_params"] = {
        "text": "Sube el peso",
        "font": DEFAULT_CONFIG["hook_text_font"],
        "flash_frame": 15,
        "flash_frames": 6,
    }
    other_clip = _clip(1, "close", "inputs/a.mp4", 360, 640, 1.0, 2.0, 30, 1.0, 30, 60)
    edl = {"clips": [hook_clip, other_clip], "brand": None}
    manifest = {"sources": [{"src": "inputs/a.mp4"}]}

    calls: list[dict] = []

    def fake_render_segment(clip, sources_by_src, sess_dir, out_dir, *a: object, **kw):
        calls.append({"clip": clip, "out_dir": out_dir})
        return out_dir / f"seg_{clip['slot']:02d}.mp4"

    monkeypatch.setattr(
        "edl_agent.render.hook_previews.render_segment", fake_render_segment
    )

    paths = render_hook_previews(
        edl, manifest, session_dir, ["primera linea", "segunda linea"], 4, ""
    )

    assert set(paths) == {"none", "0", "1"}
    by_key = {out_dir.name: clip for clip, out_dir in (
        (c["clip"], c["out_dir"]) for c in calls
    )}
    assert "text" not in by_key["none"]["effect_params"]
    assert by_key["0"]["effect_params"]["text"] == "PRIMERA\\NLINEA"
    assert by_key["1"]["effect_params"]["text"] == "SEGUNDA\\NLINEA"
    for key in ("none", "0", "1"):
        # Flash is a separate decision made later, at the effects_preview
        # pause -- these hook-line comparison previews never carry it.
        assert "flash_frame" not in by_key[key]["effect_params"]
        assert "flash_frames" not in by_key[key]["effect_params"]
    assert all(c["clip"]["slot"] == 0 for c in calls)  # only the hook clip is rendered
