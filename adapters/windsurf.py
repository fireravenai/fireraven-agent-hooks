from __future__ import annotations

import json
import sys

from core.config import load_config, resolve_settings
from core.guardrail import GuardrailError, handle_failure, run_input_check, run_output_audit
from core.serializers import WINDSURF_INPUT_EVENTS, WINDSURF_OUTPUT_AUDIT_EVENTS, serialize_windsurf


def main() -> None:
    try:
        hook_input = json.loads(sys.stdin.read())
    except json.JSONDecodeError as exc:
        print(f"Fireraven guardrail hook: invalid hook input JSON ({exc}).", file=sys.stderr)
        sys.exit(2)

    action = hook_input.get("agent_action_name") or ""
    tool_info = hook_input.get("tool_info") or {}
    session_id = hook_input.get("trajectory_id") or hook_input.get("execution_id") or ""

    config = load_config()
    try:
        settings = resolve_settings(config)
    except ValueError as exc:
        print(f"Fireraven guardrail hook: {exc}", file=sys.stderr)
        sys.exit(2)

    if action in WINDSURF_OUTPUT_AUDIT_EVENTS:
        text = serialize_windsurf(action, tool_info)
        if text and session_id:
            try:
                run_output_audit(session_id, text)
            except Exception as exc:
                if settings["fail_closed"]:
                    handle_failure(exc, True)
        sys.exit(0)

    if action not in WINDSURF_INPUT_EVENTS:
        sys.exit(0)

    text = serialize_windsurf(action, tool_info)
    if not text:
        sys.exit(0)

    if not session_id:
        print("Fireraven guardrail hook: missing trajectory_id.", file=sys.stderr)
        sys.exit(2)

    try:
        run_input_check(session_id, text, label="Windsurf Cascade")
    except Exception as exc:
        handle_failure(exc, settings["fail_closed"])
        return

    sys.exit(0)


if __name__ == "__main__":
    main()
