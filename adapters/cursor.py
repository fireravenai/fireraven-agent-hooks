from __future__ import annotations

import json
import sys

from core.config import load_config, resolve_settings
from core.guardrail import GuardrailError, run_input_check
from core.hook_io import read_hook_input
from core.human_override import OverrideDecision, log_override_audit, request_human_override
from core.serializers import CURSOR_AUDIT_EVENTS, CURSOR_INPUT_EVENTS, serialize_cursor

CURSOR_OVERRIDE_EVENTS = {
    "beforeShellExecution",
    "beforeMCPExecution",
    "beforeReadFile",
    "preToolUse",
    "subagentStart",
}

CURSOR_KNOWN_EVENTS = CURSOR_INPUT_EVENTS | CURSOR_AUDIT_EVENTS

# Covered by dedicated Cursor hooks; skip duplicate FireGuard on preToolUse.
_PRETOOL_DEFER_TOOLS = frozenset({"shell", "read"})


def pretool_deferred_to_specialized(tool_name: str) -> bool:
    """True when a specialized Cursor hook already screens this tool."""
    name = (tool_name or "").strip()
    if not name:
        return False
    lower = name.lower()
    if lower in _PRETOOL_DEFER_TOOLS:
        return True
    # Cursor MCP tools often appear as "MCP:..." / "mcp__...".
    if lower.startswith("mcp:") or lower.startswith("mcp__"):
        return True
    return False


def _allow(hook_event: str) -> None:
    if hook_event == "beforeSubmitPrompt":
        print(json.dumps({"continue": True}))
    elif hook_event == "afterFileEdit":
        # afterFileEdit has no decision control; empty success is fine.
        print("{}")
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

    for key in CURSOR_KNOWN_EVENTS:
        if key in payload:
            return key

    if "prompt" in payload:
        return "beforeSubmitPrompt"
    if "task" in payload or "subagent_type" in payload:
        return "subagentStart"
    if ("file_path" in payload or "path" in payload) and "edits" in payload:
        return "afterFileEdit"
    if "tool_name" in payload and "tool_input" in payload and "output" not in payload:
        return "beforeMCPExecution"
    if "command" in payload and "output" not in payload:
        return "beforeShellExecution"
    if ("file_path" in payload or "path" in payload) and "edits" not in payload:
        return "beforeReadFile"
    if "tool_name" in payload and ("tool_input" in payload or "input" in payload):
        return "preToolUse"

    return ""


def _handle_policy_block(hook_event: str, session_id: str, exc: GuardrailError) -> None:
    message = str(exc)
    if hook_event not in CURSOR_OVERRIDE_EVENTS or not exc.overridable:
        _deny(hook_event, message)

    decision = request_human_override("Fireraven FireGuard", message)
    log_override_audit(
        session_id=session_id,
        event=hook_event,
        decision=decision.value,
        message=message,
    )
    if decision == OverrideDecision.ALLOW:
        _allow(hook_event)
    _deny(hook_event, message)


def main() -> None:
    try:
        hook_input = read_hook_input()
    except json.JSONDecodeError:
        _deny("beforeSubmitPrompt", "Fireraven guardrail hook: invalid hook input JSON.")

    hook_event = infer_cursor_event(hook_input)

    if hook_event not in CURSOR_KNOWN_EVENTS:
        _allow(hook_event or "beforeSubmitPrompt")

    if hook_event == "preToolUse" and pretool_deferred_to_specialized(
        str(hook_input.get("tool_name") or "")
    ):
        _allow(hook_event)

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

    if hook_event in CURSOR_AUDIT_EVENTS:
        try:
            run_input_check(session_id, text, label="Cursor")
        except GuardrailError as exc:
            audit_log = {
                "session_id": session_id,
                "event": hook_event,
                "is_safe": False,
                "message": str(exc),
            }
            print(json.dumps(audit_log), file=sys.stderr)
        except Exception as exc:
            if fail_closed:
                print(
                    json.dumps(
                        {
                            "session_id": session_id,
                            "event": hook_event,
                            "error": str(exc),
                        }
                    ),
                    file=sys.stderr,
                )
        _allow(hook_event)

    try:
        run_input_check(session_id, text, label="Cursor")
    except GuardrailError as exc:
        _handle_policy_block(hook_event, session_id, exc)
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
