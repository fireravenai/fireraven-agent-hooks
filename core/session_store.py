from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.config import hooks_root


def state_dir() -> Path:
    path = hooks_root() / "state"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _path(session_id: str) -> Path:
    safe_id = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in session_id)
    return state_dir() / f"{safe_id}.json"


def load(session_id: str) -> dict[str, Any]:
    path = _path(session_id)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save(session_id: str, data: dict[str, Any]) -> None:
    path = _path(session_id)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)


def update(session_id: str, **fields: Any) -> dict[str, Any]:
    data = load(session_id)
    data.update(fields)
    save(session_id, data)
    return data


def append_history(session_id: str, role: str, content: str, limit: int = 20) -> None:
    data = load(session_id)
    history = data.get("messages_history") or []
    history.append({"role": role, "content": content})
    data["messages_history"] = history[-limit:]
    save(session_id, data)


def get_messages_history(session_id: str, current_user_text: str) -> list[dict[str, str]]:
    data = load(session_id)
    history = list(data.get("messages_history") or [])
    history.append({"role": "user", "content": current_user_text})
    return history
