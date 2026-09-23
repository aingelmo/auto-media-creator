"""Session file serving: library symlinks resolve, escapes 404."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from edl_agent.web.routes import files


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(files, "SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(files, "CACHE_DIR", tmp_path / "cache")
    sdir = tmp_path / "sessions" / "s1"
    (sdir / "inputs").mkdir(parents=True)
    (tmp_path / "cache").mkdir(parents=True)
    return sdir


def test_serves_session_symlink_into_other_session(tmp_path, monkeypatch) -> None:
    sdir = _setup(tmp_path, monkeypatch)
    target = tmp_path / "sessions" / "s2" / "inputs" / "clip.MOV"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"x")
    (sdir / "inputs" / "clip.MOV").symlink_to(target)

    resp = files.session_file("s1", "inputs/clip.MOV")

    assert Path(resp.path) == target.resolve()


def test_serves_proxy_symlink_into_cache(tmp_path, monkeypatch) -> None:
    sdir = _setup(tmp_path, monkeypatch)
    target = tmp_path / "cache" / "abc" / "proxy.mp4"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"p")
    (sdir / "proxies").mkdir(exist_ok=True)
    (sdir / "proxies" / "clip.mp4").symlink_to(target)

    resp = files.session_file("s1", "proxies/clip.mp4")

    assert Path(resp.path) == target.resolve()


def test_rejects_dotdot_and_outside_var(tmp_path, monkeypatch) -> None:
    sdir = _setup(tmp_path, monkeypatch)
    outside = tmp_path / "secret.txt"
    outside.write_bytes(b"s")
    (sdir / "inputs" / "evil").symlink_to(outside)

    with pytest.raises(HTTPException) as exc:
        files.session_file("s1", "../manifest.json")
    assert exc.value.status_code == 404

    with pytest.raises(HTTPException):
        files.session_file("s1", "inputs/evil")

    with pytest.raises(HTTPException):
        files.session_file("s1", "inputs/missing.MOV")
