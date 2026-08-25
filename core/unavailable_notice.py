from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys

from core.session_store import load, update

UNAVAILABLE_MESSAGE = "FireGuard unavailable"
_STATE_KEY = "fg_unavailable_noticed"


def consume_unavailable_notice(session_id: str) -> str | None:
    """Return the notice message once per session; None on later calls."""
    if not session_id:
        session_id = "unknown-session"
    state = load(session_id)
    if state.get(_STATE_KEY):
        return None
    update(session_id, **{_STATE_KEY: True})
    return UNAVAILABLE_MESSAGE


def show_unavailable_toast(message: str) -> None:
    """Best-effort non-blocking OS notification. Never raises."""
    try:
        system = platform.system()
        if system == "Darwin":
            _macos_toast(message)
        elif system == "Windows":
            _windows_toast(message)
        else:
            _linux_toast(message)
    except Exception:
        return


def emit_unavailable_notice(session_id: str) -> str | None:
    """Log + toast once per session. Returns the message when emitted, else None."""
    message = consume_unavailable_notice(session_id)
    if message is None:
        return None
    print(
        json.dumps(
            {
                "session_id": session_id,
                "event": "fireguard_unavailable",
                "message": message,
            }
        ),
        file=sys.stderr,
    )
    show_unavailable_toast(message)
    return message


def _linux_toast(message: str) -> None:
    if not shutil.which("notify-send"):
        return
    subprocess.Popen(
        ["notify-send", "--urgency=normal", "--expire-time=5000", "Fireraven", message],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _macos_toast(message: str) -> None:
    safe = message.replace("\\", "\\\\").replace('"', '\\"')
    subprocess.Popen(
        [
            "osascript",
            "-e",
            f'display notification "{safe}" with title "Fireraven"',
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _windows_toast(message: str) -> None:
    # Non-blocking balloon via NotifyIcon (not MessageBox).
    safe = message.replace("'", "''")
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "Add-Type -AssemblyName System.Drawing; "
        "$n = New-Object System.Windows.Forms.NotifyIcon; "
        "$n.Icon = [System.Drawing.SystemIcons]::Information; "
        "$n.Visible = $true; "
        f"$n.ShowBalloonTip(5000, 'Fireraven', '{safe}', "
        "[System.Windows.Forms.ToolTipIcon]::Info); "
        "Start-Sleep -Milliseconds 600; "
        "$n.Dispose()"
    )
    subprocess.Popen(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
