from __future__ import annotations

import json
import sys

from core.config import load_config, resolve_settings
from core.guardrail import GuardrailError, run_input_check
from core.serializers import CURSOR_INPUT_EVENTS, serialize_cursor


def _allow(hook_event: str) -> None:
    if hook_event == "beforeSubmitPrompt":
        print(json.dumps({"continue": True}))
    else:
        print(json.dumps({"permission": "allow"}))
    sys.exit(0)


def _deny(hook_event: str, message: str) -> None:
    if hook_event == "beforeSubmitPrompt":
        print(json.dumps({"continue": False, "user_message": message}))
    else:
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


def infer_cursor_event(payload: dict) -> str:
    explicit = payload.get("hook_event_name") or payload.get("event") or ""
    if explicit:
        return explicit

    for key in CURSOR_INPUT_EVENTS:
        if key in payload:
            return key

    if "prompt" in payload:
        return "beforeSubmitPrompt"
    if "tool_name" in payload and "tool_input" in payload and "output" not in payload:
        return "beforeMCPExecution"
    if "command" in payload and "output" not in payload:
        return "beforeShellExecution"
    if ("file_path" in payload or "path" in payload) and "edits" not in payload:
        return "beforeReadFile"
    if "tool_name" in payload and ("tool_input" in payload or "input" in payload):
        return "preToolUse"

    return ""


def read_hook_input() -> dict:
    raw = sys.stdin.buffer.read()
    if not raw:
        raise json.JSONDecodeError("empty stdin", "", 0)

    text = raw.decode("utf-8-sig", errors="replace").strip()
    if not text:
        raise json.JSONDecodeError("empty stdin", "", 0)

    return json.loads(text)


def main() -> None:
    try:
        hook_input = read_hook_input()
    except json.JSONDecodeError:
        _deny("beforeSubmitPrompt", "Fireraven guardrail hook: invalid hook input JSON.")

    hook_event = infer_cursor_event(hook_input)

    if hook_event not in CURSOR_INPUT_EVENTS:
        _allow(hook_event or "beforeSubmitPrompt")

    text = serialize_cursor(hook_event, hook_input)
    if not text:
        _allow(hook_event)

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
            _deny(hook_event, f"Fireraven guardrail hook: {exc}")
        _allow(hook_event)

    try:
        run_input_check(session_id, text, label="Cursor")
    except GuardrailError as exc:
        _deny(hook_event, str(exc))
    except Exception as exc:
        if fail_closed:
            _deny(hook_event, f"Fireraven guardrail hook: {exc}")
        _allow(hook_event)

    _allow(hook_event)


def settings_fail_closed(config: dict) -> bool:
    try:
        return resolve_settings(config)["fail_closed"]
    except ValueError:
        return True


if __name__ == "__main__":
    main()
