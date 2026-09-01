from __future__ import annotations

import json
import os
import sys

from core.config import fail_closed_from_config, load_config, resolve_settings
from core.guardrail import (
    FireguardUnavailableError,
    GuardrailError,
    handle_service_failure,
    resolve_service_failure,
    run_input_check,
)
from core.hook_io import read_hook_input
from core.human_override import OverrideDecision, log_override_audit, resolve_override
from core.serializers import infer_claude_event, serialize_claude
from core.unavailable_notice import emit_unavailable_notice

# GUI hosts where native permissionDecision:ask is unreliable or has no TTY prompt.
_OS_DIALOG_ENTRYPOINTS = frozenset({"claude-vscode", "claude-desktop"})


def invoked_from_cursor(payload: dict) -> bool:
    """True when Cursor runs this script via third-party Claude Code hooks.

    Cursor can load ~/.claude/settings.json hooks alongside ~/.cursor/hooks.json.
    Fireraven installs both agents separately; under Cursor only cursor_guardrail
    should enforce. Claude Code never sends cursor_version / CURSOR_VERSION.
    """
    if payload.get("cursor_version"):
        return True
    if (payload.get("cursorVersion") or "").strip():
        return True
    return bool(os.environ.get("CURSOR_VERSION", "").strip())


def _use_os_dialog_override() -> bool:
    """True for VS Code plugin and Claude Code Desktop; false for terminal CLI."""
    entry = os.environ.get("CLAUDE_CODE_ENTRYPOINT", "").strip().lower()
    return entry in _OS_DIALOG_ENTRYPOINTS


def _ask_pretool(message: str) -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "ask",
                    "permissionDecisionReason": message,
                }
            }
        )
    )
    sys.exit(0)


def _deny_pretool(message: str) -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": message,
                }
            }
        )
    )
    sys.exit(0)


def _deny_exit(message: str) -> None:
    print(message, file=sys.stderr)
    sys.exit(2)


def _post_tool_warn(message: str) -> None:
    print(
        json.dumps(
            {
                "systemMessage": message,
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": message,
                },
            }
        )
    )
    sys.exit(0)


def main() -> None:
    try:
        hook_input = read_hook_input()
    except json.JSONDecodeError as exc:
        print(f"Fireraven guardrail hook: invalid hook input JSON ({exc}).", file=sys.stderr)
        sys.exit(2)

    # Cursor third-party bridge: defer to native Cursor Fireraven hooks.
    if invoked_from_cursor(hook_input):
        sys.exit(0)

    hook_event = infer_claude_event(hook_input)
    text = serialize_claude(hook_input)
    if not text:
        sys.exit(0)

    session_id = (
        hook_input.get("session_id")
        or hook_input.get("conversation_id")
        or hook_input.get("trajectory_id")
        or "claude-session"
    )

    config = load_config()
    try:
        settings = resolve_settings(config)
    except ValueError as exc:
        if fail_closed_from_config(config):
            print(f"Fireraven guardrail hook: {exc}", file=sys.stderr)
            sys.exit(2)
        emit_unavailable_notice(session_id, reason="not_configured")
        sys.exit(0)

    if hook_event == "PostToolUse":
        try:
            run_input_check(session_id, text, label="Claude Code")
        except GuardrailError as exc:
            print(
                json.dumps(
                    {
                        "session_id": session_id,
                        "event": "PostToolUse",
                        "is_safe": False,
                        "message": str(exc),
                    }
                ),
                file=sys.stderr,
            )
            _post_tool_warn(str(exc))
        except FireguardUnavailableError as exc:
            if settings["fail_closed"]:
                print(f"Fireraven guardrail hook: {exc}", file=sys.stderr)
                _post_tool_warn(str(exc))
            else:
                notice = emit_unavailable_notice(session_id, reason=exc.reason)
                if notice:
                    _post_tool_warn(notice)
        except Exception as exc:
            if settings["fail_closed"]:
                print(f"Fireraven guardrail hook: {exc}", file=sys.stderr)
                _post_tool_warn(f"Fireraven guardrail hook: {exc}")
            else:
                notice = emit_unavailable_notice(
                    session_id,
                    reason=resolve_service_failure(exc),
                )
                if notice:
                    _post_tool_warn(notice)
        sys.exit(0)

    try:
        run_input_check(session_id, text, label="Claude Code")
    except FireguardUnavailableError as exc:
        handle_service_failure(exc, fail_closed=settings["fail_closed"], session_id=session_id)
    except GuardrailError as exc:
        message = str(exc)
        if hook_event == "PreToolUse" and exc.overridable:
            if _use_os_dialog_override():
                decision = resolve_override(
                    title="Fireraven FireGuard",
                    message=message,
                    session_id=session_id,
                    event=hook_event,
                    overridable=True,
                    event_allows_override=True,
                )
                if decision == OverrideDecision.ALLOW:
                    sys.exit(0)
                _deny_pretool(message)
            log_override_audit(
                session_id=session_id,
                event=hook_event,
                decision="ask",
                message=message,
            )
            _ask_pretool(message)
        _deny_exit(message)
    except Exception as exc:
        handle_service_failure(exc, fail_closed=settings["fail_closed"], session_id=session_id)

    sys.exit(0)


if __name__ == "__main__":
    main()
