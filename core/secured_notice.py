from __future__ import annotations

from core.session_store import load, update
from core.unavailable_notice import show_unavailable_toast

SECURED_MESSAGE = "Conversation secured by Fireraven"

_STATE_KEY = "fg_secured_noticed"


def consume_secured_notice(session_id: str) -> str | None:
    """Return the secured message once per session; None on later calls."""
    if not session_id:
        session_id = "unknown-session"
    state = load(session_id)
    if state.get(_STATE_KEY):
        return None
    update(session_id, **{_STATE_KEY: True})
    return SECURED_MESSAGE


def emit_secured_notice(session_id: str) -> str | None:
    """Toast once per session. Returns the message when emitted, else None."""
    message = consume_secured_notice(session_id)
    if message is None:
        return None
    show_unavailable_toast(message)
    return message
