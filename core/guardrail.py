from __future__ import annotations

import json
import sys
from typing import Any

from core.config import load_config, resolve_settings
from core.fireraven_client import (
    check_input_guardrail,
    check_output_guardrail,
    classify_api_error,
    ensure_conversation,
    violation_message,
)
from core.session_store import append_history, get_messages_history, load, update
from core.unavailable_notice import emit_unavailable_notice


class GuardrailError(Exception):
    """Raised when an action must be blocked.

    ``overridable`` is True for FireGuard policy/security violations (human may
    approve once). Local sensitive-path blocks are not overridable.
    """

    def __init__(self, message: str, *, overridable: bool = True) -> None:
        super().__init__(message)
        self.overridable = overridable


class FireguardUnavailableError(Exception):
    """Raised when FireGuard cannot run (config, credits, or service outage)."""

    def __init__(self, message: str = "", *, reason: str = "unavailable") -> None:
        super().__init__(message or reason)
        self.reason = reason


def resolve_service_failure(exc: Exception) -> str:
    """Return notice reason for an infrastructure failure."""
    if isinstance(exc, FireguardUnavailableError):
        return exc.reason
    return classify_api_error(exc)


def handle_service_failure(
    exc: Exception,
    *,
    fail_closed: bool,
    session_id: str,
) -> str | None:
    """If fail-open: emit notice and return message. If fail-closed: exit 2."""
    if fail_closed:
        detail = str(exc) or resolve_service_failure(exc)
        print(f"Fireraven guardrail hook: {detail}", file=sys.stderr)
        sys.exit(2)
    reason = resolve_service_failure(exc)
    return emit_unavailable_notice(session_id or "unknown-session", reason=reason)


def _settings() -> dict[str, Any]:
    config = load_config()
    try:
        settings = resolve_settings(config)
    except ValueError as exc:
        raise FireguardUnavailableError(str(exc), reason="not_configured") from exc

    if not settings["api_key"]:
        raise FireguardUnavailableError(
            "FIRERAVEN_GUARDRAILS_API_KEY is not configured.",
            reason="not_configured",
        )
    if not settings["project_id"]:
        raise FireguardUnavailableError(
            "FIRERAVEN_PROJECT_ID is not configured.",
            reason="not_configured",
        )
    return settings


def run_input_check(session_id: str, text: str, label: str) -> dict:
    if text.startswith("__LOCAL_BLOCK__:"):
        raise GuardrailError(text.split(":", 1)[1], overridable=False)

    settings = _settings()
    state = load(session_id)
    conversation_id = state.get("conversation_id")
    if not conversation_id:
        conversation_id = ensure_conversation(
            settings["api_url"],
            settings["api_key"],
            settings["project_id"],
            session_id,
            settings["timeout_sec"],
            label=label,
        )

    messages_history = get_messages_history(session_id, text)
    result = check_input_guardrail(
        settings["api_url"],
        settings["api_key"],
        conversation_id,
        messages_history,
        settings["execution_mode"],
        settings["timeout_sec"],
    )

    input_id = (result.get("input_request") or {}).get("id")
    update(
        session_id,
        conversation_id=conversation_id,
        last_input_id=input_id,
    )
    append_history(session_id, "user", text)

    if result.get("is_safe") is not True:
        raise GuardrailError(violation_message(result))

    return result


def run_output_audit(session_id: str, output_text: str) -> dict | None:
    if not output_text.strip():
        return None

    settings = _settings()
    state = load(session_id)
    conversation_id = state.get("conversation_id")
    input_id = state.get("last_input_id")
    if not conversation_id or not input_id:
        return None

    result = check_output_guardrail(
        settings["api_url"],
        settings["api_key"],
        conversation_id,
        input_id,
        output_text,
        settings["execution_mode"],
        settings["timeout_sec"],
    )
    append_history(session_id, "assistant", output_text)

    if result.get("is_safe") is not True:
        audit_log = {
            "session_id": session_id,
            "is_safe": False,
            "message": violation_message(result, "Output policy violation detected."),
        }
        print(json.dumps(audit_log), file=sys.stderr)
    return result


def handle_failure(exc: Exception, fail_closed: bool, session_id: str = "") -> None:
    if isinstance(exc, GuardrailError):
        print(str(exc), file=sys.stderr)
        sys.exit(2)
    handle_service_failure(exc, fail_closed=fail_closed, session_id=session_id)
    sys.exit(0)
