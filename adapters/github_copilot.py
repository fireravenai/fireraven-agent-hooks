from __future__ import annotations

import json
import sys

from core.config import load_config, resolve_settings
from core.guardrail import GuardrailError, run_input_check, run_output_audit
from core.serializers import (
    GITHUB_COPILOT_INPUT_EVENTS,
    GITHUB_COPILOT_OUTPUT_AUDIT_EVENTS,
    serialize_github_copilot,
)

_EVENT_ALIASES = {
    "userpromptsubmit": "userPromptSubmitted",
    "pretooluse": "preToolUse",
    "posttooluse": "postToolUse",
}


def infer_github_copilot_event(payload: dict) -> str:
    explicit = payload.get("hook_event_name") or payload.get("event") or ""
    if explicit:
        normalized = _EVENT_ALIASES.get(explicit.lower(), explicit)
        if normalized in GITHUB_COPILOT_INPUT_EVENTS | GITHUB_COPILOT_OUTPUT_AUDIT_EVENTS:
            return normalized

    if payload.get("toolResult") is not None or payload.get("tool_result") is not None:
        return "postToolUse"
    if payload.get("toolName") is not None or payload.get("tool_name") is not None:
        return "preToolUse"
    if payload.get("prompt") is not None:
        return "userPromptSubmitted"
    return ""


def read_hook_input() -> dict:
    raw = sys.stdin.buffer.read()
    if not raw:
        raise json.JSONDecodeError("empty stdin", "", 0)

    text = raw.decode("utf-8-sig", errors="replace").strip()
    if not text:
        raise json.JSONDecodeError("empty stdin", "", 0)

    return json.loads(text)


def _allow() -> None:
    sys.exit(0)


def _deny(message: str) -> None:
    print(
        json.dumps(
            {
                "permissionDecision": "deny",
                "permissionDecisionReason": message,
            }
        )
    )
    sys.exit(0)


def _fail_closed(message: str) -> None:
    print(message, file=sys.stderr)
    sys.exit(1)


def main() -> None:
    try:
        hook_input = read_hook_input()
    except json.JSONDecodeError:
        _fail_closed("Fireraven guardrail hook: invalid hook input JSON.")

    hook_event = infer_github_copilot_event(hook_input)
    if hook_event not in GITHUB_COPILOT_INPUT_EVENTS | GITHUB_COPILOT_OUTPUT_AUDIT_EVENTS:
        _allow()

    text = serialize_github_copilot(hook_event, hook_input)
    session_id = (
        hook_input.get("sessionId")
        or hook_input.get("session_id")
        or "github-copilot-session"
    )

    if hook_event in GITHUB_COPILOT_OUTPUT_AUDIT_EVENTS:
        if text:
            try:
                run_output_audit(session_id, text)
            except Exception:
                pass
        _allow()

    if not text:
        _allow()

    config = load_config()
    try:
        settings = resolve_settings(config)
        fail_closed = settings["fail_closed"]
    except ValueError as exc:
        if hook_event == "preToolUse":
            _deny(f"Fireraven guardrail hook: {exc}")
        _allow()

    try:
        run_input_check(session_id, text, label="GitHub Copilot")
    except GuardrailError as exc:
        if hook_event == "preToolUse":
            _deny(str(exc))
        print(str(exc), file=sys.stderr)
        _allow()
    except Exception as exc:
        if hook_event == "preToolUse" and fail_closed:
            _deny(f"Fireraven guardrail hook: {exc}")
        if hook_event == "preToolUse":
            _fail_closed(f"Fireraven guardrail hook: {exc}")
        print(f"Fireraven guardrail hook: {exc}", file=sys.stderr)
        _allow()

    _allow()


if __name__ == "__main__":
    main()
