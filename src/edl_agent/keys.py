"""Operator-supplied LLM API keys persisted in the runtime data volume.

Keys entered once in the web Settings page land in
`CONFIG_DIR/llm_keys.json` (`0600`), so they survive container recreates
and reinstalls — unlike process env, which is ephemeral. Resolution order
everywhere is: explicit argument > environment variable > stored file.

Only providers that need a key appear in `PROVIDER_API_KEY_ENV`
(`ollama` serves locally and needs none). `gemini` also honours the
`GOOGLE_API_KEY` alias the SDK itself accepts.
"""

from __future__ import annotations

import contextlib
import json
import os
from typing import TYPE_CHECKING

from edl_agent.paths import CONFIG_DIR

if TYPE_CHECKING:
    from pathlib import Path

# Provider -> env var holding its key. Single source of truth, re-exported
# by `edl_agent.web.state` for the session preflight.
PROVIDER_API_KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "gemini": "GEMINI_API_KEY",
}

KEYS_FILENAME = "llm_keys.json"


def _keys_path() -> Path:
    """Return the persisted-keys file path (under the data volume)."""
    return CONFIG_DIR / KEYS_FILENAME


def _write_keys(data: dict[str, str]) -> None:
    """Write `data` to the keys file atomically with `0600` permissions."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    path = _keys_path()
    tmp = path.with_name(f"{path.stem}.tmp.{os.getpid()}{path.suffix}")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(path)


def stored_keys() -> dict[str, str]:
    """Read the UI-persisted keys file.

    Returns:
        Mapping of provider to key. Empty when no keys were ever saved
        or the file is unreadable/corrupt (a corrupt file is treated as
        absent rather than failing every pipeline run).
    """
    try:
        data = json.loads(_keys_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if isinstance(k, str) and v}


def resolve_api_key(provider: str, explicit: str | None = None) -> str | None:
    """Resolve the effective API key for `provider`.

    Args:
        provider: LLM provider name (e.g. `"deepseek"`).
        explicit: Per-call override (e.g. a key typed into a form);
            wins when non-blank.

    Returns:
        The key, or `None` when neither an explicit value, the env var,
        nor the persisted file provides one. Unknown/keyless providers
        (e.g. `"ollama"`) always resolve to `None`.
    """
    if explicit and explicit.strip():
        return explicit.strip()
    env_names = (
        [PROVIDER_API_KEY_ENV[provider]] if provider in PROVIDER_API_KEY_ENV else []
    )
    if provider == "gemini":
        env_names.append("GOOGLE_API_KEY")
    for name in env_names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    stored = stored_keys().get(provider, "").strip()
    return stored or None


def keys_configured() -> dict[str, dict[str, bool | str]]:
    """Report per-provider key availability without exposing secrets.

    Returns:
        Mapping of provider to `{"configured": bool, "source": str}`
        where `source` is `"explicit"`-never (only env/server/none are
        observable here): `"env"` when an environment variable provides
        the key, `"server"` when the persisted file does, `"none"`
        otherwise.
    """
    stored = stored_keys()
    out: dict[str, dict[str, bool | str]] = {}
    for provider, env_name in PROVIDER_API_KEY_ENV.items():
        if os.environ.get(env_name, "").strip() or (
            provider == "gemini" and os.environ.get("GOOGLE_API_KEY", "").strip()
        ):
            out[provider] = {"configured": True, "source": "env"}
        elif stored.get(provider, "").strip():
            out[provider] = {"configured": True, "source": "server"}
        else:
            out[provider] = {"configured": False, "source": "none"}
    return out


def store_api_key(provider: str, api_key: str) -> None:
    """Persist `api_key` for `provider` in the data volume (`0600`).

    Args:
        provider: Must be a key of `PROVIDER_API_KEY_ENV`.
        api_key: Non-blank key; surrounding whitespace is stripped.

    Raises:
        ValueError: If `provider` needs no key or `api_key` is blank.
    """
    if provider not in PROVIDER_API_KEY_ENV:
        msg = (
            f"unknown provider {provider!r}, "
            f"expected one of {sorted(PROVIDER_API_KEY_ENV)}"
        )
        raise ValueError(msg)
    if not api_key.strip():
        msg = f"blank API key for provider {provider!r}"
        raise ValueError(msg)
    data = stored_keys()
    data[provider] = api_key.strip()
    _write_keys(data)


def clear_api_key(provider: str) -> bool:
    """Remove the persisted key for `provider`.

    Args:
        provider: Must be a key of `PROVIDER_API_KEY_ENV`.

    Returns:
        `True` when a stored key existed and was removed.

    Raises:
        ValueError: If `provider` needs no key.
    """
    if provider not in PROVIDER_API_KEY_ENV:
        msg = (
            f"unknown provider {provider!r}, "
            f"expected one of {sorted(PROVIDER_API_KEY_ENV)}"
        )
        raise ValueError(msg)
    data = stored_keys()
    if provider not in data:
        return False
    del data[provider]
    if not data:
        with contextlib.suppress(OSError):
            _keys_path().unlink()
        return True
    _write_keys(data)
    return True
