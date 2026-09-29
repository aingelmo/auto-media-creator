"""UI-persisted LLM API keys: resolution order, store/clear, settings routes."""

from __future__ import annotations

import json
import stat
from typing import Any

import pytest
from fastapi import HTTPException

from edl_agent import keys
from edl_agent.keys import (
    clear_api_key,
    keys_configured,
    resolve_api_key,
    store_api_key,
)
from edl_agent.web.routes import settings


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Point the keys file at a scratch dir with a clean environment."""
    monkeypatch.setattr(keys, "CONFIG_DIR", tmp_path / "config")
    for env in ("DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY",
                "GOOGLE_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    return tmp_path


def test_resolve_prefers_explicit_over_env_and_file(isolated, monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
    store_api_key("deepseek", "stored-key")
    assert resolve_api_key("deepseek", explicit="typed-key") == "typed-key"


def test_resolve_prefers_env_over_file(isolated, monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
    store_api_key("deepseek", "stored-key")
    assert resolve_api_key("deepseek") == "env-key"


def test_resolve_falls_back_to_file(isolated) -> None:
    store_api_key("deepseek", "stored-key")
    assert resolve_api_key("deepseek") == "stored-key"


def test_resolve_none_when_nothing_configured(isolated) -> None:
    assert resolve_api_key("deepseek") is None
    assert resolve_api_key("ollama") is None


def test_resolve_gemini_alias_env(isolated, monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "google-key")
    assert resolve_api_key("gemini") == "google-key"


def test_store_writes_0600_and_roundtrips(isolated) -> None:
    store_api_key("deepseek", "  sk-123  ")
    path = isolated / "config" / "llm_keys.json"
    assert path.read_text() == json.dumps({"deepseek": "sk-123"}, indent=2)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert keys_configured()["deepseek"] == {"configured": True, "source": "server"}


def test_status_reports_env_source(isolated, monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
    assert keys_configured()["deepseek"] == {"configured": True, "source": "env"}
    assert keys_configured()["anthropic"] == {"configured": False, "source": "none"}


def test_store_rejects_unknown_provider_and_blank_key(isolated) -> None:
    with pytest.raises(ValueError):
        store_api_key("ollama", "x")
    with pytest.raises(ValueError):
        store_api_key("deepseek", "   ")
    with pytest.raises(ValueError):
        clear_api_key("ollama")


def test_corrupt_file_resolves_to_nothing(isolated) -> None:
    config = isolated / "config"
    config.mkdir(parents=True)
    (config / "llm_keys.json").write_text("not json{")
    assert resolve_api_key("deepseek") is None
    assert keys.stored_keys() == {}


def test_clear_removes_key_and_empty_file(isolated) -> None:
    store_api_key("deepseek", "sk-123")
    assert clear_api_key("deepseek") is True
    assert not (isolated / "config" / "llm_keys.json").exists()
    assert clear_api_key("deepseek") is False


def test_settings_routes_roundtrip(isolated) -> None:
    assert settings.get_keys()["deepseek"]["configured"] is False
    out = settings.put_key(settings.KeyBody(provider="deepseek", api_key="sk-1"))
    assert out == {"provider": "deepseek", "configured": True, "source": "server"}
    assert settings.get_keys()["deepseek"]["configured"] is True
    out = settings.delete_key("deepseek")
    assert out["configured"] is False


def test_settings_routes_reject_bad_input(isolated) -> None:
    with pytest.raises(HTTPException) as exc:
        settings.put_key(settings.KeyBody(provider="nope", api_key="x"))
    assert exc.value.status_code == 400
    with pytest.raises(HTTPException) as exc:
        settings.put_key(settings.KeyBody(provider="deepseek", api_key="  "))
    assert exc.value.status_code == 400
    with pytest.raises(HTTPException) as exc:
        settings.delete_key("nope")
    assert exc.value.status_code == 400


def test_get_client_injects_stored_key(isolated, monkeypatch) -> None:
    import edl_agent.llm.deepseek_client as deepseek_module
    from edl_agent.llm import get_client

    store_api_key("deepseek", "stored-key")
    seen: dict = {}

    def recorder(**kwargs):
        seen.update(kwargs)
        return "client"

    monkeypatch.setattr(deepseek_module, "deepseek_client", recorder)
    assert get_client("deepseek") == "client"
    assert seen == {"api_key": "stored-key"}


def test_get_client_passes_no_key_when_unconfigured(isolated, monkeypatch) -> None:
    import edl_agent.llm.ollama_client as ollama_module
    from edl_agent.llm import get_client

    real = ollama_module.OllamaClient
    seen: dict = {}

    def recorder(*args: Any, **kwargs: Any):
        seen.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(ollama_module, "OllamaClient", recorder)
    get_client("ollama")
    assert seen == {}
