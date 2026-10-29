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
    run_output_audit,
)
from core.hook_io import read_hook_input
from core.human_override import OverrideDecision, resolve_override
from core.serializers import USER_PROMPT_EVENTS, infer_devin_event, serialize_devin
from core.unavailable_notice import emit_unavailable_notice


def _approve() -> None:
    print(json.dumps({"decision": "approve"}))
    sys.exit(0)


def _block(message: str) -> None:
    print(json.dumps({"decision": "block", "reason": message}))
    sys.exit(0)


def _deny_exit(message: str) -> None:
    print(message, file=sys.stderr)
    sys.exit(2)


def main() -> None:
    try:
        hook_input = read_hook_input()
    except json.JSONDecodeError as exc:
        print(f"Fireraven guardrail hook: invalid hook input JSON ({exc}).", file=sys.stderr)
        sys.exit(2)

    hook_event = infer_devin_event(hook_input)
    text = serialize_devin(hook_input)
    if not text:
        sys.exit(0)

    session_id = (
        hook_input.get("session_id")
        or hook_input.get("prompt_id")
        or hook_input.get("conversation_id")
        or "devin-session"
    )

    config = load_config()
    try:
        settings = resolve_settings(config)
    except ValueError as exc:
        if fail_closed_from_config(config):
            if hook_event in ("PreToolUse", "UserPromptSubmit"):
                _block(f"Fireraven guardrail hook: {exc}")
            print(f"Fireraven guardrail hook: {exc}", file=sys.stderr)
            sys.exit(2)
        emit_unavailable_notice(session_id, reason="not_configured")
        sys.exit(0)

    if hook_event == "PostToolUse":
        try:
            run_output_audit(session_id, text)
        except FireguardUnavailableError as exc:
            if settings["fail_closed"]:
                print(f"Fireraven guardrail hook: {exc}", file=sys.stderr)
            else:
                emit_unavailable_notice(session_id, reason=exc.reason)
        except Exception as exc:
            if settings["fail_closed"]:
                print(f"Fireraven guardrail hook: {exc}", file=sys.stderr)
            else:
                emit_unavailable_notice(session_id, reason=resolve_service_failure(exc))
        sys.exit(0)

    if hook_event not in ("PreToolUse", "UserPromptSubmit"):
        sys.exit(0)

    try:
        run_input_check(
            session_id,
            text,
            label="Devin Local",
            enforce_pii=hook_event in USER_PROMPT_EVENTS,
        )
    except FireguardUnavailableError as exc:
        if settings["fail_closed"]:
            if hook_event == "PreToolUse":
                _block(str(exc))
            _deny_exit(str(exc))
        emit_unavailable_notice(session_id, reason=exc.reason)
        sys.exit(0)
    except GuardrailError as exc:
        message = str(exc)
        if hook_event == "PreToolUse":
            decision = resolve_override(
                title="Fireraven FireGuard",
                message=message,
                session_id=session_id,
                event=hook_event,
                overridable=exc.overridable,
                event_allows_override=True,
            )
            if decision == OverrideDecision.ALLOW:
                _approve()
            _block(message)
        _deny_exit(message)
    except Exception as exc:
        if settings["fail_closed"]:
            if hook_event == "PreToolUse":
                _block(f"Fireraven guardrail hook: {exc}")
            _deny_exit(f"Fireraven guardrail hook: {exc}")
        emit_unavailable_notice(session_id, reason=resolve_service_failure(exc))
        sys.exit(0)

    sys.exit(0)


if __name__ == "__main__":
    main()
