"""Relative symlinks for cache links and library refs (#3 storage split)."""

from __future__ import annotations

import shutil

from edl_agent.ingest.cache import link_into
from edl_agent.web.routes import files, sessions


def test_link_into_creates_relative_symlink(tmp_path) -> None:
    cache_file = tmp_path / "cache" / "abc" / "proxy.mp4"
    cache_file.parent.mkdir(parents=True)
    cache_file.write_bytes(b"p")
    session_path = tmp_path / "sessions" / "s1" / "proxies" / "a.mp4"

    link_into(session_path, cache_file)

    assert session_path.is_symlink()
    assert not session_path.readlink().is_absolute()
    assert session_path.resolve() == cache_file.resolve()


def test_link_into_survives_root_move(tmp_path) -> None:
    root = tmp_path / "var"
    cache_file = root / "cache" / "abc" / "proxy.mp4"
    cache_file.parent.mkdir(parents=True)
    cache_file.write_bytes(b"p")
    session_path = root / "sessions" / "s1" / "proxies" / "a.mp4"
    link_into(session_path, cache_file)

    moved = tmp_path / "mnt-elsewhere"
    shutil.move(str(root), str(moved))

    assert (moved / "sessions" / "s1" / "proxies" / "a.mp4").resolve() == (
        moved / "cache" / "abc" / "proxy.mp4"
    ).resolve()


def test_link_ref_creates_relative_symlink(tmp_path, monkeypatch) -> None:
    sessions_dir = tmp_path / "sessions"
    src = sessions_dir / "old" / "inputs" / "clip.MOV"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"x")
    monkeypatch.setattr(sessions, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(files, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(files, "CACHE_DIR", tmp_path / "cache")

    sessions._link_ref(
        "old/inputs/clip.MOV", sessions_dir / "new" / "inputs", "clip.MOV"
    )

    dest = sessions_dir / "new" / "inputs" / "clip.MOV"
    assert dest.is_symlink()
    assert not dest.readlink().is_absolute()
    assert dest.resolve() == src.resolve()
    resp = files.session_file("new", "inputs/clip.MOV")
    assert resp.path is not None
