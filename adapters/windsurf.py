from __future__ import annotations

import json
import sys

from core.config import load_config, resolve_settings
from core.guardrail import GuardrailError, handle_failure, run_input_check, run_output_audit
from core.hook_io import read_hook_input
from core.human_override import OverrideDecision, resolve_override
from core.serializers import WINDSURF_INPUT_EVENTS, WINDSURF_OUTPUT_AUDIT_EVENTS, serialize_windsurf

# Tool pre-hooks may show an OS Allow/Deny dialog. Prompts stay hard deny.
WINDSURF_OVERRIDE_EVENTS = {
    "pre_run_command",
    "pre_mcp_tool_use",
    "pre_write_code",
    "pre_read_code",
}


def main() -> None:
    try:
        hook_input = read_hook_input()
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
                    handle_failure(exc, True, session_id)
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
    except GuardrailError as exc:
        message = str(exc)
        decision = resolve_override(
            title="Fireraven FireGuard",
            message=message,
            session_id=session_id or "windsurf-session",
            event=action,
            overridable=exc.overridable,
            event_allows_override=action in WINDSURF_OVERRIDE_EVENTS,
        )
        if decision == OverrideDecision.ALLOW:
            sys.exit(0)
        print(message, file=sys.stderr)
        sys.exit(2)
    except Exception as exc:
        handle_failure(exc, settings["fail_closed"], session_id)
        return

    sys.exit(0)


if __name__ == "__main__":
    main()
