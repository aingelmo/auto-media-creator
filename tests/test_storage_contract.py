"""Storage contract: runtime data stays under VAR, dirs boot ready."""

from __future__ import annotations

import os

import pytest

from edl_agent import paths
from edl_agent.startup import (
    VENDOR_ENV_DEFAULTS,
    ensure_runtime_dirs,
    ensure_vendor_cache_env,
)


def test_runtime_dirs_created_and_writable(tmp_path) -> None:
    root = ensure_runtime_dirs(tmp_path / "var")
    for name in ("sessions", "cache", "models", "trash", "config"):
        assert (root / name).is_dir()


def test_runtime_dirs_fail_fast_on_unwritable_mount(tmp_path) -> None:
    if os.geteuid() == 0:
        pytest.skip("root bypasses directory permissions")
    var = tmp_path / "var"
    (var / "sessions").mkdir(parents=True)
    (var / "sessions").chmod(0o555)
    with pytest.raises(RuntimeError, match="not writable"):
        ensure_runtime_dirs(var)


def test_vendor_cache_env_defaults_under_volume(tmp_path, monkeypatch) -> None:
    for env_var in VENDOR_ENV_DEFAULTS:
        monkeypatch.delenv(env_var, raising=False)
    ensure_vendor_cache_env(tmp_path / "var")
    for env_var in VENDOR_ENV_DEFAULTS:
        assert os.environ[env_var].startswith(str(tmp_path / "var" / "cache"))


def test_vendor_cache_env_never_overrides_operator(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TORCH_HOME", "/operator/torch")
    monkeypatch.delenv("ULTRALYTICS_SETTINGS_DIR", raising=False)
    ensure_vendor_cache_env(tmp_path / "var")
    assert os.environ["TORCH_HOME"] == "/operator/torch"
    assert os.environ["ULTRALYTICS_SETTINGS_DIR"].startswith(
        str(tmp_path / "var" / "cache")
    )


def test_var_subdirs_match_startup_contract() -> None:
    assert paths.SESSIONS_DIR == paths.VAR / "sessions"
    assert paths.CACHE_DIR == paths.VAR / "cache"
    assert paths.MODELS_DIR == paths.VAR / "models"
    assert paths.TRASH_DIR == paths.VAR / "trash"
    assert paths.CONFIG_DIR == paths.VAR / "config"
