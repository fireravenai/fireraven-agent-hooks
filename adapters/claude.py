from __future__ import annotations

import json
import sys

from core.config import load_config, resolve_settings
from core.guardrail import GuardrailError, run_input_check
from core.serializers import serialize_claude


def main() -> None:
    try:
        hook_input = json.loads(sys.stdin.read())
    except json.JSONDecodeError as exc:
        print(f"Fireraven guardrail hook: invalid hook input JSON ({exc}).", file=sys.stderr)
        sys.exit(2)

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
        print(f"Fireraven guardrail hook: {exc}", file=sys.stderr)
        sys.exit(2)

    try:
        run_input_check(session_id, text, label="Claude Code")
    except GuardrailError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
    except Exception as exc:
        if settings["fail_closed"]:
            print(f"Fireraven guardrail hook: {exc}", file=sys.stderr)
            sys.exit(2)
        sys.exit(0)

    sys.exit(0)


if __name__ == "__main__":
    main()
