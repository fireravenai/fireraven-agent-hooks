from __future__ import annotations

import json
import sys

from core.config import load_config, resolve_settings
from core.guardrail import GuardrailError, run_input_check
from core.serializers import CURSOR_INPUT_EVENTS, serialize_cursor


def _allow() -> None:
    print(json.dumps({"permission": "allow"}))
    sys.exit(0)


def _deny(message: str) -> None:
    print(
        json.dumps(
            {
                "permission": "deny",
                "user_message": message,
                "agent_message": message,
            }
        )
    )
    sys.exit(0)


def main() -> None:
    try:
        hook_input = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        _deny("Fireraven guardrail hook: invalid hook input JSON.")

    hook_event = hook_input.get("hook_event_name") or hook_input.get("event") or ""
    if not hook_event:
        for key in CURSOR_INPUT_EVENTS:
            if key in hook_input:
                hook_event = key
                break

    if hook_event not in CURSOR_INPUT_EVENTS:
        _allow()

    text = serialize_cursor(hook_event, hook_input)
    if not text:
        _allow()

    session_id = (
        hook_input.get("conversation_id")
        or hook_input.get("trajectory_id")
        or hook_input.get("session_id")
        or "cursor-session"
    )

    config = load_config()
    try:
        settings = resolve_settings(config)
        fail_closed = settings["fail_closed"]
    except ValueError as exc:
        if settings_fail_closed(config):
            _deny(f"Fireraven guardrail hook: {exc}")
        _allow()

    try:
        run_input_check(session_id, text, label="Cursor")
    except GuardrailError as exc:
        _deny(str(exc))
    except Exception as exc:
        if fail_closed:
            _deny(f"Fireraven guardrail hook: {exc}")
        _allow()


def settings_fail_closed(config: dict) -> bool:
    try:
        return resolve_settings(config)["fail_closed"]
    except ValueError:
        return True


if __name__ == "__main__":
    main()
