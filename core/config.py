from __future__ import annotations

import os
from pathlib import Path

DEFAULT_API_URL = "https://api.fireraven.ai"
DEFAULT_EXECUTION_MODE = "fast"
DEFAULT_TIMEOUT_SEC = 15


def hooks_root() -> Path:
    env_root = os.environ.get("FIRERAVEN_HOOKS_ROOT", "").strip()
    if env_root:
        return Path(env_root)
    return Path(__file__).resolve().parent.parent


def config_path() -> Path:
    override = os.environ.get("FIRERAVEN_CONFIG_PATH", "").strip()
    if override:
        return Path(override)
    return hooks_root() / "config.env"


def load_config() -> dict[str, str]:
    path = config_path()
    config: dict[str, str] = {}
    if not path.is_file():
        return config

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        config[key.strip()] = value.strip()
    return config


def get_setting(config: dict[str, str], key: str, default: str = "") -> str:
    return config.get(key) or os.environ.get(key, default)


def resolve_settings(config: dict[str, str]) -> dict[str, str | float]:
    timeout_raw = get_setting(config, "FIRERAVEN_REQUEST_TIMEOUT_SEC", str(DEFAULT_TIMEOUT_SEC))
    try:
        timeout_sec = float(timeout_raw)
    except ValueError as exc:
        raise ValueError("FIRERAVEN_REQUEST_TIMEOUT_SEC must be a number") from exc

    api_key = get_setting(config, "FIRERAVEN_GUARDRAILS_API_KEY")
    project_id = get_setting(config, "FIRERAVEN_PROJECT_ID")
    api_url = get_setting(config, "FIRERAVEN_API_URL", DEFAULT_API_URL)
    execution_mode = get_setting(config, "FIRERAVEN_EXECUTION_MODE", DEFAULT_EXECUTION_MODE)
    fail_mode = get_setting(config, "FIRERAVEN_FAIL_MODE", "closed").lower()

    return {
        "api_key": api_key,
        "project_id": project_id,
        "api_url": api_url,
        "execution_mode": execution_mode,
        "timeout_sec": timeout_sec,
        "fail_closed": fail_mode != "open",
    }
