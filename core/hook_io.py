"""Shared stdin JSON parsing for agent hook adapters."""

from __future__ import annotations

import json
import sys


def read_hook_input() -> dict:
    """Read hook JSON from stdin, tolerating a UTF-8 BOM (common on Windows)."""
    raw = sys.stdin.buffer.read()
    if not raw:
        raise json.JSONDecodeError("empty stdin", "", 0)

    text = raw.decode("utf-8-sig", errors="replace").strip()
    if not text:
        raise json.JSONDecodeError("empty stdin", "", 0)

    return json.loads(text)
