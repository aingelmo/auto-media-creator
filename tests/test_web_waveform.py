"""Waveform peak extraction and the lazy `/api/media/peaks` ref guard."""

from __future__ import annotations

import array
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from edl_agent.ingest import waveform
from edl_agent.web.routes import waveform as route


def _pcm(*values: int) -> bytes:
    samples = array.array("h", values)
    return samples.tobytes()


def test_extract_peaks_reduces_to_buckets_in_unit_range(monkeypatch) -> None:
    # 8 samples, 4 buckets: bucket peaks are 8192, 16384, 24576, 32767.
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            stdout=_pcm(1, -8192, 3, 16384, -5, 24576, 7, -32767)
        ),
    )

    peaks = waveform.extract_peaks(Path("track.mp3"), buckets=4)

    assert len(peaks) == 4
    assert peaks == pytest.approx([0.25, 0.5, 0.75, 1.0])
    assert all(0.0 <= p <= 1.0 for p in peaks)


def test_extract_peaks_empty_track_yields_no_buckets(monkeypatch) -> None:
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=b""))

    assert waveform.extract_peaks(Path("silent.mp3")) == []


def test_resolve_ref_accepts_music_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(route, "SESSIONS_DIR", tmp_path)
    src = tmp_path / "s1" / "music" / "track.mp3"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"x")

    assert route._resolve_ref("s1/music/track.mp3") == src.resolve()


@pytest.mark.parametrize(
    "ref",
    [
        "s1/../../secret.mp3",
        "/etc/passwd",
        "s1/inputs/clip.mp4",
        "s1/music",
        "s1/music/missing.mp3",
        "not-a-ref",
    ],
)
def test_resolve_ref_rejects_bad_refs(tmp_path, monkeypatch, ref) -> None:
    monkeypatch.setattr(route, "SESSIONS_DIR", tmp_path)
    (tmp_path / "s1" / "music").mkdir(parents=True)
    (tmp_path / "s1" / "inputs").mkdir(parents=True)
    (tmp_path / "s1" / "inputs" / "clip.mp4").write_bytes(b"x")

    with pytest.raises(HTTPException) as exc:
        route._resolve_ref(ref)
    assert exc.value.status_code == 404


def test_media_peaks_caches_and_reuses_extraction(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(route, "SESSIONS_DIR", tmp_path)
    monkeypatch.setattr(route, "_PEAKS_CACHE_PATH", tmp_path / "peaks.json")
    src = tmp_path / "s1" / "music" / "track.mp3"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"x")
    calls = []

    def fake_extract(path, **kwargs):
        calls.append((path, kwargs))
        return [0.1, 0.9]

    monkeypatch.setattr(route, "extract_peaks", fake_extract)

    first = route.media_peaks("s1/music/track.mp3")
    second = route.media_peaks("s1/music/track.mp3")

    assert first["peaks"] == second["peaks"] == [0.1, 0.9]
    assert first["start_s"] is None and first["end_s"] is None
    assert len(calls) == 1


def test_media_peaks_empty_on_decode_failure(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(route, "SESSIONS_DIR", tmp_path)
    monkeypatch.setattr(route, "_PEAKS_CACHE_PATH", tmp_path / "peaks.json")
    src = tmp_path / "s1" / "music" / "broken.mp3"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"x")

    def boom(path, **kwargs):
        raise subprocess.CalledProcessError(1, "ffmpeg")

    monkeypatch.setattr(route, "extract_peaks", boom)

    assert route.media_peaks("s1/music/broken.mp3")["peaks"] == []


def test_extract_peaks_range_seeks_with_ffmpeg(monkeypatch) -> None:
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return SimpleNamespace(stdout=_pcm(1000, -2000, 3000, -4000))

    monkeypatch.setattr(subprocess, "run", fake_run)

    peaks = waveform.extract_peaks(
        Path("track.mp3"), buckets=2, start_s=10.0, window_s=5.0
    )

    assert len(peaks) == 2
    assert "-ss" in seen["cmd"] and "-t" in seen["cmd"]
    assert seen["cmd"][seen["cmd"].index("-ss") + 1] == "10.0"


def test_media_peaks_ranged_request_caches_separately(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(route, "SESSIONS_DIR", tmp_path)
    monkeypatch.setattr(route, "_PEAKS_CACHE_PATH", tmp_path / "peaks.json")
    src = tmp_path / "s1" / "music" / "track.mp3"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"x")
    calls = []

    def fake_extract(path, **kwargs):
        calls.append(kwargs)
        return [0.5]

    monkeypatch.setattr(route, "extract_peaks", fake_extract)

    full = route.media_peaks("s1/music/track.mp3")
    zoom = route.media_peaks("s1/music/track.mp3", buckets=64, start_s=30.0, end_s=45.0)

    assert full["start_s"] is None
    assert zoom["start_s"] == 30.0 and zoom["end_s"] == 45.0
    assert calls[1]["buckets"] == 64
    assert calls[1]["start_s"] == 30.0 and calls[1]["window_s"] == 15.0


def test_measure_loudness_parses_volumedetect(monkeypatch) -> None:
    stderr = (
        "[Parsed_volumedetect_0] mean_volume: -14.5 dB\n"
        "[Parsed_volumedetect_0] max_volume: -1.0 dB\n"
    )
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: SimpleNamespace(stderr=stderr)
    )

    loud = waveform.measure_loudness(Path("track.mp3"))

    assert loud["mean_volume_db"] == -14.5
    assert loud["max_volume_db"] == -1.0
    assert loud["peak"] == pytest.approx(10.0 ** (-1.0 / 20.0), rel=1e-3)


def test_measure_loudness_silence_yields_nones(monkeypatch) -> None:
    stderr = (
        "[Parsed_volumedetect_0] mean_volume: n/a\n"
        "[Parsed_volumedetect_0] max_volume: n/a\n"
    )
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: SimpleNamespace(stderr=stderr)
    )

    loud = waveform.measure_loudness(Path("silent.mp3"))

    assert loud["mean_volume_db"] is None
    assert loud["max_volume_db"] is None
    assert loud["peak"] == 0.0


def test_media_loudness_caches_per_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(route, "SESSIONS_DIR", tmp_path)
    monkeypatch.setattr(route, "_LOUD_CACHE_PATH", tmp_path / "loud.json")
    src = tmp_path / "s1" / "music" / "track.mp3"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"x")
    calls = []

    def fake_measure(path):
        calls.append(path)
        return {"mean_volume_db": -12.0, "max_volume_db": -2.0, "peak": 0.8}

    monkeypatch.setattr(route, "measure_loudness", fake_measure)

    first = route.media_loudness("s1/music/track.mp3")
    second = route.media_loudness("s1/music/track.mp3")

    assert first == second
    assert len(calls) == 1
