from __future__ import annotations

import json
import sys

from core.config import load_config, resolve_settings
from core.guardrail import GuardrailError, run_input_check, run_output_audit
from core.hook_io import read_hook_input
from core.human_override import OverrideDecision, resolve_override
from core.serializers import infer_devin_event, serialize_devin


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
        if hook_event in ("PreToolUse", "UserPromptSubmit"):
            _block(f"Fireraven guardrail hook: {exc}")
        print(f"Fireraven guardrail hook: {exc}", file=sys.stderr)
        sys.exit(2)

    if hook_event == "PostToolUse":
        try:
            run_output_audit(session_id, text)
        except Exception as exc:
            if settings["fail_closed"]:
                print(f"Fireraven guardrail hook: {exc}", file=sys.stderr)
        sys.exit(0)

    if hook_event not in ("PreToolUse", "UserPromptSubmit"):
        sys.exit(0)

    try:
        run_input_check(session_id, text, label="Devin Local")
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
        sys.exit(0)

    sys.exit(0)


if __name__ == "__main__":
    main()
