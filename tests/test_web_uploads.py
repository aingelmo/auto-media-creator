"""Chunked-upload API: init/chunk/complete lifecycle and session linking."""

from __future__ import annotations

import hashlib
import os
import time

from fastapi.testclient import TestClient

from edl_agent.web.app import app
from edl_agent.web.routes import sessions, uploads


def _patch_dirs(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    sess = tmp_path / "sessions"
    cache.mkdir()
    sess.mkdir()
    monkeypatch.setattr(uploads, "CACHE_DIR", cache)
    monkeypatch.setattr(uploads, "SESSIONS_DIR", sess)
    monkeypatch.setattr(sessions, "SESSIONS_DIR", sess)
    return cache, sess


def test_round_trip_clip(tmp_path, monkeypatch) -> None:
    _, sess = _patch_dirs(tmp_path, monkeypatch)
    monkeypatch.setattr(uploads, "CHUNK_SIZE", 8192)
    client = TestClient(app)
    payload = os.urandom(20_000)
    digest = hashlib.sha256(payload).hexdigest()

    init = client.post(
        "/api/uploads/init",
        json={
            "session_name": "s1",
            "kind": "clip",
            "filename": "a.mp4",
            "size": len(payload),
            "sha256": digest,
        },
    )
    assert init.status_code == 200, init.text
    upload_id = init.json()["upload_id"]
    assert init.json()["chunk_size"] == 8192

    offset = 0
    index = 0
    while offset < len(payload):
        piece = payload[offset : offset + 8192]
        res = client.put(
            f"/api/uploads/{upload_id}/chunk?index={index}&offset={offset}",
            content=piece,
            headers={"Content-Type": "application/octet-stream"},
        )
        assert res.status_code == 200, res.text
        offset += len(piece)
        index += 1
    assert res.json()["done"] is True
    done = client.post(f"/api/uploads/{upload_id}/complete")
    assert done.status_code == 200, done.text
    assert done.json()["ref"] == "s1/inputs/a.mp4"
    assert (sess / "s1" / "inputs" / "a.mp4").read_bytes() == payload


def test_round_trip_aligned_chunks(tmp_path, monkeypatch) -> None:
    _patch_dirs(tmp_path, monkeypatch)
    client = TestClient(app)
    # monkeypatch chunk size small so multi-chunk flow is exercised.
    monkeypatch.setattr(uploads, "CHUNK_SIZE", 4)
    payload = b"abcdefgh"
    init = client.post(
        "/api/uploads/init",
        json={"session_name": "s1", "kind": "music", "filename": "t.mp3", "size": 8},
    )
    upload_id = init.json()["upload_id"]
    assert (
        client.put(
            f"/api/uploads/{upload_id}/chunk?index=0&offset=0",
            content=payload[:4],
            headers={"Content-Type": "application/octet-stream"},
        ).status_code
        == 200
    )
    assert (
        client.put(
            f"/api/uploads/{upload_id}/chunk?index=1&offset=4",
            content=payload[4:],
            headers={"Content-Type": "application/octet-stream"},
        ).status_code
        == 200
    )
    done = client.post(f"/api/uploads/{upload_id}/complete")
    assert done.status_code == 200
    assert done.json()["ref"] == "s1/music/t.mp3"


def test_chunk_offset_mismatch_is_409(tmp_path, monkeypatch) -> None:
    _patch_dirs(tmp_path, monkeypatch)
    client = TestClient(app)
    init = client.post(
        "/api/uploads/init",
        json={"session_name": "s1", "kind": "clip", "filename": "a.mp4", "size": 10},
    )
    upload_id = init.json()["upload_id"]
    assert (
        client.put(
            f"/api/uploads/{upload_id}/chunk?index=0&offset=0",
            content=b"12345",
            headers={"Content-Type": "application/octet-stream"},
        ).status_code
        == 200
    )
    bad = client.put(
        f"/api/uploads/{upload_id}/chunk?index=0&offset=0",
        content=b"xxxxx",
        headers={"Content-Type": "application/octet-stream"},
    )
    assert bad.status_code == 409


def test_init_bad_extension_is_400(tmp_path, monkeypatch) -> None:
    _patch_dirs(tmp_path, monkeypatch)
    client = TestClient(app)
    res = client.post(
        "/api/uploads/init",
        json={"session_name": "s1", "kind": "clip", "filename": "evil.exe", "size": 10},
    )
    assert res.status_code == 400
    res = client.post(
        "/api/uploads/init",
        json={"session_name": "s1", "kind": "clip", "filename": "../x.mp4", "size": 10},
    )
    assert res.status_code == 400


def test_complete_missing_chunks_is_400(tmp_path, monkeypatch) -> None:
    _patch_dirs(tmp_path, monkeypatch)
    client = TestClient(app)
    init = client.post(
        "/api/uploads/init",
        json={"session_name": "s1", "kind": "clip", "filename": "a.mp4", "size": 10},
    )
    upload_id = init.json()["upload_id"]
    client.put(
        f"/api/uploads/{upload_id}/chunk?index=0&offset=0",
        content=b"12345",
        headers={"Content-Type": "application/octet-stream"},
    )
    done = client.post(f"/api/uploads/{upload_id}/complete")
    assert done.status_code == 400


def test_abandoned_upload_expiry(tmp_path, monkeypatch) -> None:
    cache, _ = _patch_dirs(tmp_path, monkeypatch)
    client = TestClient(app)
    stale = cache / "uploads" / "stale123"
    stale.mkdir(parents=True)
    (stale / "meta.json").write_text("{}")
    old = time.time() - uploads.UPLOAD_TTL_S - 10
    os.utime(stale, (old, old))
    client.post(
        "/api/uploads/init",
        json={"session_name": "s1", "kind": "clip", "filename": "a.mp4", "size": 5},
    )
    assert not stale.exists()


def test_session_links_completed_uploads(tmp_path, monkeypatch) -> None:
    import asyncio
    from unittest.mock import Mock

    _, sess = _patch_dirs(tmp_path, monkeypatch)
    client = TestClient(app)

    def _upload(kind, filename, data) -> str:
        init = client.post(
            "/api/uploads/init",
            json={
                "session_name": "big",
                "kind": kind,
                "filename": filename,
                "size": len(data),
            },
        )
        uid = init.json()["upload_id"]
        client.put(
            f"/api/uploads/{uid}/chunk?index=0&offset=0",
            content=data,
            headers={"Content-Type": "application/octet-stream"},
        )
        assert client.post(f"/api/uploads/{uid}/complete").status_code == 200
        return uid

    clip_id = _upload("clip", "c.mp4", b"clipdata")
    music_id = _upload("music", "t.mp3", b"musicdata")
    monkeypatch.setattr(sessions, "jobs", {})
    tasks = Mock()
    tasks.add_task = Mock()

    out = asyncio.run(
        sessions.create_session(
            tasks,
            name="big",
            provider="ollama",
            theme="training",
            clips=[],
            music=None,
            clip_refs=[],
            music_ref="",
            logo=None,
            clip_upload_ids=[clip_id],
            music_upload_id=music_id,
            logo_upload_id="",
            handle="",
            brief="",
            audience="prospects",
        )
    )
    assert out.status_code == 200
    assert (sess / "big" / "inputs" / "c.mp4").read_bytes() == b"clipdata"
    assert (sess / "big" / "music" / "t.mp3").read_bytes() == b"musicdata"
