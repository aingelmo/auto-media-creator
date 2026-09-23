"""Media-library listing (dedupe), picker-ref containment, and delete endpoint."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from edl_agent.web import trash
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
    assert entries[0]["mtime"] > 0


def test_scan_attaches_proxy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(media, "SESSIONS_DIR", tmp_path)
    monkeypatch.setattr(media, "_META_CACHE_PATH", tmp_path / "meta.json")
    monkeypatch.setattr(
        media,
        "_probe_file",
        lambda path, audio_only=False: {
            "duration_s": 10.0,
            "w": 720,
            "h": 1280,
            "kind": "video",
        },
    )
    d = tmp_path / "s1" / "inputs"
    d.mkdir(parents=True)
    (d / "clip.MOV").write_bytes(b"x")
    (tmp_path / "s1" / "proxies").mkdir(parents=True)
    (tmp_path / "s1" / "proxies" / "clip.mp4").write_bytes(b"p")
    (tmp_path / "s1" / "manifest.json").write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "src": "inputs/clip.MOV",
                        "proxy": "proxies/clip.mp4",
                        "proxy_verified": True,
                    }
                ]
            }
        )
    )
    (tmp_path / "s1" / "inputs" / "bare.MOV").write_bytes(b"y")

    entries = {e["filename"]: e for e in media._scan("inputs", {".mov"})}

    assert entries["clip.MOV"]["proxy_path"] == "proxies/clip.mp4"
    assert entries["clip.MOV"]["proxy_verified"] is True
    assert entries["bare.MOV"]["proxy_path"] is None
    assert entries["bare.MOV"]["proxy_verified"] is False


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


def _make_session(tmp_path, name="s1") -> None:
    sdir = tmp_path / name
    (sdir / "inputs").mkdir(parents=True)
    (sdir / "inputs" / "a.mp4").write_bytes(b"aaa")
    (sdir / "inputs" / "b.mp4").write_bytes(b"bbb")
    (sdir / "proxies").mkdir(exist_ok=True)
    (sdir / "proxies" / "a.mp4").write_bytes(b"proxy")
    (sdir / "inputs_norm").mkdir(exist_ok=True)
    (sdir / "inputs_norm" / "a.jpg").write_bytes(b"norm")
    (sdir / "music").mkdir(exist_ok=True)
    (sdir / "music" / "track.mp3").write_bytes(b"mmm")
    manifest = {
        "session_id": name,
        "sources": [
            {"src": "inputs/a.mp4", "type": "video"},
            {"src": "inputs/b.mp4", "type": "video"},
        ],
        "music": {"src": "music/track.mp3"},
    }
    (sdir / "manifest.json").write_text(json.dumps(manifest))
    (sdir / "candidates.json").write_text("{}")
    (sdir / "edl.json").write_text("{}")


def _patch_dirs(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(media, "SESSIONS_DIR", tmp_path)
    monkeypatch.setattr(media, "_META_CACHE_PATH", tmp_path / "meta.json")
    monkeypatch.setattr(media, "jobs", {})
    monkeypatch.setattr(trash, "SESSIONS_DIR", tmp_path)
    monkeypatch.setattr(trash, "TRASH_DIR", tmp_path / "trash")


def test_delete_clip_removes_file_derived_manifest_and_stages(
    tmp_path, monkeypatch
) -> None:
    _patch_dirs(tmp_path, monkeypatch)
    _make_session(tmp_path)

    out = media.delete_media(ref="s1/inputs/a.mp4")

    assert out["ref"] == "s1/inputs/a.mp4"
    assert out["item"]["kind"] == "media"
    # The payload moved into the bin, not unlinked.
    assert not (tmp_path / "s1" / "inputs" / "a.mp4").exists()
    assert (tmp_path / "trash" / out["item"]["id"] / "payload").is_file()
    assert (tmp_path / "s1" / "inputs" / "b.mp4").exists()
    assert not (tmp_path / "s1" / "proxies" / "a.mp4").exists()
    assert not (tmp_path / "s1" / "inputs_norm" / "a.jpg").exists()
    manifest = json.loads((tmp_path / "s1" / "manifest.json").read_text())
    assert [s["src"] for s in manifest["sources"]] == ["inputs/b.mp4"]
    assert not (tmp_path / "s1" / "candidates.json").exists()
    assert not (tmp_path / "s1" / "edl.json").exists()


def test_delete_unlinks_symlink_and_keeps_original(tmp_path, monkeypatch) -> None:
    _patch_dirs(tmp_path, monkeypatch)
    _make_session(tmp_path, name="s1")
    sdir2 = tmp_path / "s2"
    (sdir2 / "inputs").mkdir(parents=True)
    (sdir2 / "inputs" / "b.mp4").write_bytes(b"other")
    (sdir2 / "inputs" / "linked.mp4").symlink_to(
        (tmp_path / "s1" / "inputs" / "a.mp4").resolve()
    )
    (sdir2 / "music").mkdir(exist_ok=True)
    (sdir2 / "music" / "track.mp3").write_bytes(b"mmm")

    out = media.delete_media(ref="s2/inputs/linked.mp4")

    assert not (sdir2 / "inputs" / "linked.mp4").exists()
    # The moved payload is still a symlink whose target survives in s1.
    payload = tmp_path / "trash" / out["item"]["id"] / "payload"
    assert payload.is_symlink()
    assert (tmp_path / "s1" / "inputs" / "a.mp4").exists()


def test_delete_music_drops_track_cut_and_manifest_music(
    tmp_path, monkeypatch,
) -> None:
    _patch_dirs(tmp_path, monkeypatch)
    _make_session(tmp_path)
    (tmp_path / "s1" / "music" / "extra.wav").write_bytes(b"e")
    (tmp_path / "s1" / "music" / "track_cut.wav").write_bytes(b"cut")

    out = media.delete_media(ref="s1/music/track.mp3")

    assert not (tmp_path / "s1" / "music" / "track.mp3").exists()
    assert (tmp_path / "trash" / out["item"]["id"] / "payload").is_file()
    assert not (tmp_path / "s1" / "music" / "track_cut.wav").exists()
    manifest = json.loads((tmp_path / "s1" / "manifest.json").read_text())
    assert "music" not in manifest


def test_delete_blocked_while_job_running(tmp_path, monkeypatch) -> None:
    _patch_dirs(tmp_path, monkeypatch)
    _make_session(tmp_path)
    monkeypatch.setattr(media, "jobs", {"s1": SimpleNamespace(done=False)})

    with pytest.raises(HTTPException) as exc:
        media.delete_media(ref="s1/inputs/a.mp4")
    assert exc.value.status_code == 409
    assert (tmp_path / "s1" / "inputs" / "a.mp4").exists()


def test_delete_blocked_for_last_clip_and_only_track(
    tmp_path, monkeypatch,
) -> None:
    _patch_dirs(tmp_path, monkeypatch)
    _make_session(tmp_path)
    (tmp_path / "s1" / "inputs" / "b.mp4").unlink()

    with pytest.raises(HTTPException) as exc:
        media.delete_media(ref="s1/inputs/a.mp4")
    assert exc.value.status_code == 400

    with pytest.raises(HTTPException) as exc:
        media.delete_media(ref="s1/music/track.mp3")
    assert exc.value.status_code == 400


def test_delete_rejects_generated_and_traversal(tmp_path, monkeypatch) -> None:
    _patch_dirs(tmp_path, monkeypatch)
    _make_session(tmp_path)

    with pytest.raises(HTTPException) as exc:
        media.delete_media(ref="s1/music/track_cut.wav")
    assert exc.value.status_code == 400

    with pytest.raises(HTTPException) as exc:
        media.delete_media(ref="s1/../../secret.mp4")
    assert exc.value.status_code in (400, 404)

    with pytest.raises(HTTPException) as exc:
        media.delete_media(ref="s1/inputs/missing.mp4")
    assert exc.value.status_code == 404


def test_music_track_returns_session_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(sessions, "SESSIONS_DIR", tmp_path)
    monkeypatch.setattr(
        sessions, "ffprobe", lambda path: {"format": {"duration": "187.3"}}
    )
    music = tmp_path / "s1" / "music"
    music.mkdir(parents=True)
    (music / "track.mp3").write_bytes(b"x")
    (music / "track_cut.wav").write_bytes(b"cut")
    (music / "candidates").mkdir(exist_ok=True)
    (music / "candidates" / "cand_0.wav").write_bytes(b"c")

    out = sessions.session_music_track("s1")

    assert out["path"] == "music/track.mp3"
    assert out["filename"] == "track.mp3"
    assert out["duration_s"] == 187.3
    assert out["peaks_ref"] == "s1/music/track.mp3"


def test_music_track_missing_or_probe_failure(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(sessions, "SESSIONS_DIR", tmp_path)
    with pytest.raises(HTTPException) as exc:
        sessions.session_music_track("nope")
    assert exc.value.status_code == 404

    sdir = tmp_path / "s1" / "music"
    sdir.mkdir(parents=True)
    (sdir / "track_cut.wav").write_bytes(b"cut")
    with pytest.raises(HTTPException) as exc:
        sessions.session_music_track("s1")
    assert exc.value.status_code == 404

    (sdir / "track.mp3").write_bytes(b"x")

    def boom(path):
        raise OSError

    monkeypatch.setattr(sessions, "ffprobe", boom)
    out = sessions.session_music_track("s1")
    assert out["duration_s"] is None
