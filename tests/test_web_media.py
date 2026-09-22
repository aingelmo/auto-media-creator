"""Media-library listing (dedupe) and picker-ref containment checks."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from edl_agent.web.routes import media, sessions


def test_scan_dedupes_by_filename_and_size_newest_first(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(media, "SESSIONS_DIR", tmp_path)

    for name, content in [("s1", b"aaa"), ("s2", b"aaa"), ("s3", b"bb")]:
        d = tmp_path / name / "inputs"
        d.mkdir(parents=True)
        (d / "clip.mp4").write_bytes(content)

    entries = media._scan("inputs", {".mp4"})

    assert [e["session"] for e in entries] == ["s3", "s2"]
    assert entries[1]["path"] == "inputs/clip.mp4"


def test_scan_ignores_other_extensions(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(media, "SESSIONS_DIR", tmp_path)
    d = tmp_path / "s1" / "music"
    d.mkdir(parents=True)
    (d / "track.mp3").write_bytes(b"x")
    (d / "notes.txt").write_bytes(b"x")

    entries = media._scan("music", {".mp3", ".wav"})

    assert [e["filename"] for e in entries] == ["track.mp3"]


def test_link_ref_rejects_path_outside_session(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(sessions, "SESSIONS_DIR", tmp_path)
    (tmp_path / "s1").mkdir()
    outside = tmp_path.parent / "secret.mp4"
    outside.write_bytes(b"x")

    with pytest.raises(HTTPException) as exc:
        sessions._link_ref("s1/../../secret.mp4", tmp_path / "dest", "clip.mp4")
    assert exc.value.status_code == 404


def test_link_ref_symlinks_existing_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(sessions, "SESSIONS_DIR", tmp_path)
    src = tmp_path / "s1" / "inputs" / "clip.mp4"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"x")
    dest_dir = tmp_path / "s2" / "inputs"

    sessions._link_ref("s1/inputs/clip.mp4", dest_dir, "clip.mp4")

    assert (dest_dir / "clip.mp4").resolve() == src.resolve()


def test_scan_attaches_probe_meta(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(media, "SESSIONS_DIR", tmp_path)
    monkeypatch.setattr(media, "_META_CACHE_PATH", tmp_path / "meta.json")
    monkeypatch.setattr(
        media,
        "_probe_file",
        lambda path, audio_only=False: {
            "duration_s": 12.5,
            "w": 1080,
            "h": 1920,
            "kind": "audio" if audio_only else "video",
        },
    )
    d = tmp_path / "s1" / "inputs"
    d.mkdir(parents=True)
    (d / "clip.mp4").write_bytes(b"x")

    entries = media._scan("inputs", {".mp4"})

    assert entries[0]["duration_s"] == 12.5
    assert entries[0]["w"] == 1080
    assert entries[0]["h"] == 1920
    assert entries[0]["kind"] == "video"


def test_scan_caps_entries_at_limit(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(media, "SESSIONS_DIR", tmp_path)
    monkeypatch.setattr(media, "_META_CACHE_PATH", tmp_path / "meta.json")
    monkeypatch.setattr(media, "MEDIA_SCAN_LIMIT", 3)
    monkeypatch.setattr(
        media,
        "_probe_file",
        lambda path, audio_only=False: {
            "duration_s": None,
            "w": None,
            "h": None,
            "kind": "video",
        },
    )
    for i in range(5):
        d = tmp_path / f"s{i}" / "inputs"
        d.mkdir(parents=True)
        (d / f"clip{i}.mp4").write_bytes(b"x")

    assert len(media._scan("inputs", {".mp4"})) == 3


def test_list_sessions_enriched(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(sessions, "SESSIONS_DIR", tmp_path)
    monkeypatch.setattr(sessions, "session_status", lambda name: "done")
    monkeypatch.setattr(sessions, "total_cost_usd", lambda name: 0.012)
    sdir = tmp_path / "s1"
    (sdir / "inputs").mkdir(parents=True)
    (sdir / "inputs" / "a.mp4").write_bytes(b"x")
    (sdir / "inputs" / "b.jpg").write_bytes(b"x")
    (sdir / "inputs" / "notes.txt").write_bytes(b"x")
    (sdir / "music").mkdir(parents=True)
    (sdir / "music" / "track.mp3").write_bytes(b"x")
    (sdir / "music" / "track_cut.wav").write_bytes(b"x")
    (sdir / "reel.mp4").write_bytes(b"x")

    (entry,) = sessions.list_sessions()

    assert entry["name"] == "s1"
    assert entry["status"] == "done"
    assert entry["reel_exists"] is True
    assert entry["clip_count"] == 2
    assert entry["music_name"] == "track.mp3"
    assert entry["total_cost_usd"] == 0.012
    assert entry["mtime"] > 0
