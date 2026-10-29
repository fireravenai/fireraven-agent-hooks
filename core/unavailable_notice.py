from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from core.config import hooks_root
from core.session_store import load, update

UNAVAILABLE_MESSAGE = "FireGuard unavailable"
NOT_CONFIGURED_MESSAGE = "FireGuard not configured"
NO_CREDITS_MESSAGE = "FireGuard: no credits left"

NOTICE_MESSAGES: dict[str, str] = {
    "unavailable": UNAVAILABLE_MESSAGE,
    "not_configured": NOT_CONFIGURED_MESSAGE,
    "no_credits": NO_CREDITS_MESSAGE,
}

_STATE_KEY = "fg_unavailable_noticed"
_ICON_NAME = "fireraven.ico"
# Must match install.ps1 Install-FireravenToastApp AUMID (Start Menu shortcut).
_WINDOWS_TOAST_AUMID = "Fireraven.FireGuard"


def notice_message(reason: str) -> str:
    return NOTICE_MESSAGES.get(reason, UNAVAILABLE_MESSAGE)


def consume_unavailable_notice(session_id: str, reason: str = "unavailable") -> str | None:
    """Return the notice message once per session; None on later calls."""
    if not session_id:
        session_id = "unknown-session"
    state = load(session_id)
    if state.get(_STATE_KEY):
        return None
    update(session_id, **{_STATE_KEY: True})
    return notice_message(reason)


def toast_icon_path() -> Path | None:
    """Return path to Fireraven toast icon if installed; else None."""
    path = hooks_root() / "assets" / _ICON_NAME
    return path if path.is_file() else None


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


def emit_unavailable_notice(session_id: str, reason: str = "unavailable") -> str | None:
    """Log + toast once per session. Returns the message when emitted, else None."""
    message = consume_unavailable_notice(session_id, reason=reason)
    if message is None:
        return None
    print(
        json.dumps(
            {
                "session_id": session_id,
                "event": "fireguard_unavailable",
                "reason": reason,
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
    cmd = ["notify-send", "--urgency=normal", "--expire-time=5000"]
    icon = toast_icon_path()
    if icon is not None:
        cmd.extend(["-i", str(icon)])
    cmd.extend(["Fireraven", message])
    subprocess.Popen(
        cmd,
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


def _windows_launch_kwargs() -> dict:
    # CREATE_NO_WINDOW avoids a console flash. Do not use DETACHED_PROCESS —
    # it can prevent WinRT Action Center toasts from showing.
    creationflags = 0
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        creationflags |= subprocess.CREATE_NO_WINDOW
    kwargs: dict = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "stdin": subprocess.DEVNULL,
        "close_fds": True,
    }
    if creationflags:
        kwargs["creationflags"] = creationflags
    return kwargs


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _windows_toast(message: str) -> None:
    _windows_action_center_toast(message)


def _windows_action_center_toast(message: str) -> None:
    # Best-effort Action Center corner toast via WinRT (ToastGeneric).
    # AppId is Fireraven.FireGuard from the silent Start Menu shortcut (install.ps1).
    # Run via a temp -File script (no DETACHED_PROCESS); keep alive briefly after Show().
    safe = _xml_escape(message)
    icon = toast_icon_path()
    if icon is not None:
        icon_uri = icon.resolve().as_uri()
        logo = (
            f'<image placement="appLogoOverride" hint-crop="circle" '
            f'src="{_xml_escape(icon_uri)}"/>'
        )
    else:
        logo = ""
    xml = (
        "<toast>"
        '<visual><binding template="ToastGeneric">'
        "<text>Fireraven</text>"
        f"<text>{safe}</text>"
        f"{logo}"
        "</binding></visual>"
        "</toast>"
    )
    # Here-string cannot contain the terminator "'@" alone; our notice strings do not.
    ps_body = (
        "$ErrorActionPreference = 'Stop'\n"
        f"$AppId = '{_WINDOWS_TOAST_AUMID}'\n"
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
        "ContentType = WindowsRuntime] | Out-Null\n"
        "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, "
        "ContentType = WindowsRuntime] | Out-Null\n"
        "$xml = New-Object Windows.Data.Xml.Dom.XmlDocument\n"
        f"$xml.LoadXml(@'\n{xml}\n'@)\n"
        "$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)\n"
        "[Windows.UI.Notifications.ToastNotificationManager]::"
        "CreateToastNotifier($AppId).Show($toast)\n"
        "Start-Sleep -Seconds 2\n"
        "Remove-Item -LiteralPath $MyInvocation.MyCommand.Path -Force "
        "-ErrorAction SilentlyContinue\n"
    )
    fd, path = tempfile.mkstemp(prefix="fireraven_toast_", suffix=".ps1")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(ps_body)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(path)
        except OSError:
            pass
        raise
    subprocess.Popen(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", path],
        **_windows_launch_kwargs(),
    )
