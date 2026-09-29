"""ffmpeg binary resolution and filter preflight (`edl_agent.ffmpeg`)."""

from __future__ import annotations

import pytest

from edl_agent.ffmpeg import (
    FFMPEG_ENV_VAR,
    FFmpegError,
    ffmpeg_bin,
    ffprobe_bin,
    has_filter,
    require_filters,
)


@pytest.fixture(autouse=True)
def _clear_caches():
    ffmpeg_bin.cache_clear()
    ffprobe_bin.cache_clear()
    has_filter.cache_clear()
    yield
    ffmpeg_bin.cache_clear()
    ffprobe_bin.cache_clear()
    has_filter.cache_clear()


def test_ffmpeg_bin_prefers_env_override(monkeypatch, tmp_path) -> None:
    fake = tmp_path / "ffmpeg-full"
    fake.write_text("#!/bin/sh\n")
    monkeypatch.setenv(FFMPEG_ENV_VAR, str(fake))
    assert ffmpeg_bin() == str(fake)


def test_ffprobe_bin_uses_env_sibling(monkeypatch, tmp_path) -> None:
    fake_ff = tmp_path / "ffmpeg-full"
    fake_fp = tmp_path / "ffprobe"
    fake_ff.write_text("#!/bin/sh\n")
    fake_fp.write_text("#!/bin/sh\n")
    monkeypatch.setenv(FFMPEG_ENV_VAR, str(fake_ff))
    assert ffprobe_bin() == str(fake_fp)


def test_ffprobe_bin_falls_back_to_path_without_sibling(
    monkeypatch, tmp_path
) -> None:
    import shutil

    fake_ff = tmp_path / "ffmpeg-full"
    fake_ff.write_text("#!/bin/sh\n")
    monkeypatch.setenv(FFMPEG_ENV_VAR, str(fake_ff))
    assert ffprobe_bin() == (shutil.which("ffprobe") or "ffprobe")


def test_has_filter_detects_present_and_absent() -> None:
    assert has_filter("scale")
    assert not has_filter("no_such_filter_xyz")


def test_require_filters_raises_naming_binary_and_missing(monkeypatch) -> None:
    import edl_agent.ffmpeg as ffmpeg_module

    monkeypatch.setattr(
        ffmpeg_module, "has_filter", lambda name: name != "drawtext"
    )
    has_filter.cache_clear()
    with pytest.raises(FFmpegError, match="drawtext"):
        require_filters({"scale", "drawtext"})


def test_require_filters_passes_on_full_build() -> None:
    require_filters({"scale", "overlay", "drawtext", "ass", "zscale"})


def test_hook_text_filter_fails_fast_without_ass(monkeypatch, tmp_path) -> None:
    import edl_agent.render._common as common
    from edl_agent.render._common import RenderError, hook_text_filter

    monkeypatch.setattr(common, "has_filter", lambda name: False)
    clip = {"effect_params": {"text": "HOOK", "font_size": 90}}
    with pytest.raises(RenderError, match="`ass` filter"):
        hook_text_filter(clip, tmp_path / "seg_00.mp4")
    assert hook_text_filter({"effect_params": {}}, tmp_path / "seg_00.mp4") == ""
