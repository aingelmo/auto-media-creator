"""Soft-delete bin: session/media trash, restore, purge, and expiry."""

from __future__ import annotations

import json

import pytest

from edl_agent.web import trash
from edl_agent.web.routes import media, sessions


def _patch(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(trash, "SESSIONS_DIR", tmp_path)
    monkeypatch.setattr(trash, "TRASH_DIR", tmp_path / "trash")


def _make_session(tmp_path, name="s1") -> None:
    sdir = tmp_path / name
    (sdir / "inputs").mkdir(parents=True)
    (sdir / "inputs" / "a.mp4").write_bytes(b"aaa")
    (sdir / "music").mkdir(exist_ok=True)
    (sdir / "music" / "track.mp3").write_bytes(b"mmm")
    manifest = {
        "session_id": name,
        "sources": [{"src": "inputs/a.mp4", "type": "video"}],
        "music": {"src": "music/track.mp3"},
    }
    (sdir / "manifest.json").write_text(json.dumps(manifest))


def test_trash_session_moves_payload_and_lists(tmp_path, monkeypatch) -> None:
    _patch(tmp_path, monkeypatch)
    _make_session(tmp_path)

    item = trash.trash_session("s1", {"clip_count": 1})

    assert not (tmp_path / "s1").exists()
    payload = tmp_path / "trash" / item["id"] / "payload"
    assert (payload / "inputs" / "a.mp4").is_file()
    assert item["kind"] == "session"
    assert item["label"] == "s1"
    assert item["meta"]["clip_count"] == 1
    assert item["purge_after"] > item["deleted_at"]
    assert item["size_bytes"] > 0

    (listed,) = trash.list_items()
    assert listed["id"] == item["id"]


def test_restore_session_round_trips(tmp_path, monkeypatch) -> None:
    _patch(tmp_path, monkeypatch)
    _make_session(tmp_path)
    item = trash.trash_session("s1")

    restored = trash.restore_item(item["id"])

    assert restored["id"] == item["id"]
    assert (tmp_path / "s1" / "inputs" / "a.mp4").is_file()
    assert trash.list_items() == []


def test_restore_refuses_existing_destination(tmp_path, monkeypatch) -> None:
    _patch(tmp_path, monkeypatch)
    _make_session(tmp_path)
    item = trash.trash_session("s1")
    _make_session(tmp_path)  # a new session took the name back

    with pytest.raises(FileExistsError):
        trash.restore_item(item["id"])
    assert (tmp_path / "s1" / "inputs" / "a.mp4").is_file()


def test_purge_and_empty_are_final(tmp_path, monkeypatch) -> None:
    _patch(tmp_path, monkeypatch)
    _make_session(tmp_path)
    first = trash.trash_session("s1")
    (tmp_path / "s2").mkdir()
    second = trash.trash_session("s2")

    assert trash.purge_item(first["id"]) == first["id"]
    assert not (tmp_path / "trash" / first["id"]).exists()
    with pytest.raises(FileNotFoundError):
        trash.purge_item(first["id"])

    assert trash.empty() == 1
    assert trash.list_items() == []
    assert not (tmp_path / "trash" / second["id"]).exists()


def test_list_purges_expired_items(tmp_path, monkeypatch) -> None:
    _patch(tmp_path, monkeypatch)
    _make_session(tmp_path)
    item = trash.trash_session("s1")
    record_path = tmp_path / "trash" / item["id"] / "item.json"
    record = json.loads(record_path.read_text())
    record["purge_after"] = 0  # long past
    record_path.write_text(json.dumps(record))

    assert trash.list_items() == []
    assert not (tmp_path / "trash" / item["id"]).exists()


def test_item_dir_rejects_escapes(tmp_path, monkeypatch) -> None:
    _patch(tmp_path, monkeypatch)
    for bad in ("", "..", "a/b", ".hidden", "x\\y"):
        with pytest.raises(FileNotFoundError):
            trash.purge_item(bad)


def test_media_trash_round_trips_manifest(tmp_path, monkeypatch) -> None:
    _patch(tmp_path, monkeypatch)
    monkeypatch.setattr(media, "SESSIONS_DIR", tmp_path)
    _make_session(tmp_path)

    source_entry, music_entry = media._pop_manifest_entry("s1", "inputs/a.mp4")
    assert source_entry is not None
    item = trash.trash_media(
        "s1", "inputs/a.mp4", source_entry=source_entry, music_entry=music_entry
    )
    assert not (tmp_path / "s1" / "inputs" / "a.mp4").exists()
    manifest = json.loads((tmp_path / "s1" / "manifest.json").read_text())
    assert manifest["sources"] == []

    restored = trash.restore_item(item["id"])
    media.restore_media_manifest(restored)

    assert (tmp_path / "s1" / "inputs" / "a.mp4").is_file()
    manifest = json.loads((tmp_path / "s1" / "manifest.json").read_text())
    assert [s["src"] for s in manifest["sources"]] == ["inputs/a.mp4"]


def test_delete_session_route_trashes_and_drops_job(tmp_path, monkeypatch) -> None:
    from types import SimpleNamespace

    _patch(tmp_path, monkeypatch)
    monkeypatch.setattr(sessions, "SESSIONS_DIR", tmp_path)
    monkeypatch.setattr(sessions, "session_status", lambda name: "done")
    monkeypatch.setattr(sessions, "total_cost_usd", lambda name: 0.0)
    monkeypatch.setattr(sessions, "jobs", {"s1": SimpleNamespace(done=True)})
    _make_session(tmp_path)

    out = sessions.delete_session("s1")

    assert out["name"] == "s1"
    assert out["item"]["kind"] == "session"
    assert not (tmp_path / "s1").exists()
    assert "s1" not in sessions.jobs


def test_delete_session_route_blocks_running_job(tmp_path, monkeypatch) -> None:
    from types import SimpleNamespace

    from fastapi import HTTPException

    _patch(tmp_path, monkeypatch)
    monkeypatch.setattr(sessions, "SESSIONS_DIR", tmp_path)
    monkeypatch.setattr(sessions, "jobs", {"s1": SimpleNamespace(done=False)})
    _make_session(tmp_path)

    with pytest.raises(HTTPException) as exc:
        sessions.delete_session("s1")
    assert exc.value.status_code == 409
    assert (tmp_path / "s1").is_dir()
