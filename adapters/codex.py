from __future__ import annotations

import json
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
from core.human_override import OverrideDecision, resolve_override
from core.secured_notice import emit_secured_notice
from core.serializers import USER_PROMPT_EVENTS, infer_codex_event, serialize_codex
from core.unavailable_notice import emit_unavailable_notice


def _deny_pretool(message: str) -> None:
    """Block a tool call. Codex treats permissionDecision "ask" as a failed hook and continues."""
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


def _deny_prompt(message: str) -> None:
    print(json.dumps({"decision": "block", "reason": message}))
    sys.exit(0)


def _deny_exit(message: str) -> None:
    print(message, file=sys.stderr)
    sys.exit(2)


def _status(message: str) -> None:
    """Show a once-per-session notice. systemMessage is the Codex UI field; the helper already toasted."""
    print(json.dumps({"systemMessage": message}))
    sys.exit(0)


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

    hook_event = infer_codex_event(hook_input)
    text = serialize_codex(hook_input)
    if not text:
        sys.exit(0)

    session_id = (
        hook_input.get("session_id")
        or hook_input.get("conversation_id")
        or hook_input.get("trajectory_id")
        or "codex-session"
    )

    config = load_config()
    try:
        settings = resolve_settings(config)
    except ValueError as exc:
        if fail_closed_from_config(config):
            print(f"Fireraven guardrail hook: {exc}", file=sys.stderr)
            sys.exit(2)
        notice = emit_unavailable_notice(session_id, reason="not_configured")
        if notice:
            _status(notice)
        sys.exit(0)

    enforce_pii = hook_event in USER_PROMPT_EVENTS

    if hook_event == "PostToolUse":
        try:
            run_input_check(session_id, text, label="Codex", enforce_pii=False)
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
        run_input_check(session_id, text, label="Codex", enforce_pii=enforce_pii)
    except FireguardUnavailableError as exc:
        notice = handle_service_failure(
            exc, fail_closed=settings["fail_closed"], session_id=session_id
        )
        if notice:
            _status(notice)
    except GuardrailError as exc:
        message = str(exc)
        if hook_event == "PreToolUse" and exc.overridable:
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
        if hook_event == "PreToolUse":
            _deny_pretool(message)
        if hook_event == "UserPromptSubmit":
            _deny_prompt(message)
        _deny_exit(message)
    except Exception as exc:
        notice = handle_service_failure(
            exc, fail_closed=settings["fail_closed"], session_id=session_id
        )
        if notice:
            _status(notice)
    else:
        if hook_event == "UserPromptSubmit":
            notice = emit_secured_notice(session_id)
            if notice:
                _status(notice)

    sys.exit(0)


if __name__ == "__main__":
    main()
