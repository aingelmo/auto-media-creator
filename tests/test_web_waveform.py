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

    def fake_extract(path):
        calls.append(path)
        return [0.1, 0.9]

    monkeypatch.setattr(route, "extract_peaks", fake_extract)

    first = route.media_peaks("s1/music/track.mp3")
    second = route.media_peaks("s1/music/track.mp3")

    assert first == second == {"peaks": [0.1, 0.9]}
    assert len(calls) == 1


def test_media_peaks_empty_on_decode_failure(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(route, "SESSIONS_DIR", tmp_path)
    monkeypatch.setattr(route, "_PEAKS_CACHE_PATH", tmp_path / "peaks.json")
    src = tmp_path / "s1" / "music" / "broken.mp3"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"x")

    def boom(path):
        raise subprocess.CalledProcessError(1, "ffmpeg")

    monkeypatch.setattr(route, "extract_peaks", boom)

    assert route.media_peaks("s1/music/broken.mp3") == {"peaks": []}
