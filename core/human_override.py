from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from enum import Enum


class OverrideDecision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    UNAVAILABLE = "unavailable"


DEFAULT_TIMEOUT_SEC = 60

_LINUX_UNAVAILABLE_HINT = (
    "fireraven_override: no dialog available — install yad (preferred), "
    "zenity, or kdialog, and ensure DISPLAY or WAYLAND_DISPLAY is set"
)


def log_override_audit(
    *,
    session_id: str,
    event: str,
    decision: str,
    message: str,
) -> None:
    fingerprint = " ".join(message.split())[:200]
    print(
        f"fireraven_override session={session_id} event={event} "
        f"decision={decision} detail={fingerprint}",
        file=sys.stderr,
    )


def resolve_override(
    *,
    title: str,
    message: str,
    session_id: str,
    event: str,
    overridable: bool,
    event_allows_override: bool,
) -> OverrideDecision:
    """Shared gate: deny immediately, or ask the human then audit."""
    if not event_allows_override or not overridable:
        return OverrideDecision.DENY
    decision = request_human_override(title, message)
    log_override_audit(
        session_id=session_id,
        event=event,
        decision=decision.value,
        message=message,
    )
    return decision


def request_human_override(
    title: str,
    message: str,
    *,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
) -> OverrideDecision:
    """Block until the user answers an OS dialog, or return UNAVAILABLE."""
    body = (message or "FireGuard blocked this action.").strip()
    if len(body) > 1500:
        body = body[:1500] + "…"
    try:
        system = platform.system()
        if system == "Darwin":
            return _macos_dialog(title, body, timeout_sec)
        if system == "Windows":
            return _windows_dialog(title, body, timeout_sec)
        return _linux_dialog(title, body, timeout_sec)
    except Exception:
        return OverrideDecision.UNAVAILABLE


def _linux_dialog(title: str, message: str, timeout_sec: int) -> OverrideDecision:
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        print(_LINUX_UNAVAILABLE_HINT, file=sys.stderr)
        return OverrideDecision.UNAVAILABLE

    prompt = f"{message}\n\nAllow this action anyway?"

    if shutil.which("yad"):
        # Plain dialog (not --question) avoids stock icons; empty window-icon
        # clears the title-bar glyph when the toolkit allows it.
        result = subprocess.run(
            [
                "yad",
                f"--title={title}",
                f"--text={prompt}",
                "--text-align=left",
                "--window-icon=",
                "--button=Allow:0",
                "--button=Deny:1",
                "--buttons-layout=center",
                "--borders=16",
                "--width=420",
                "--center",
                f"--timeout={int(timeout_sec)}",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return OverrideDecision.ALLOW
        return OverrideDecision.DENY

    if shutil.which("zenity"):
        result = subprocess.run(
            [
                "zenity",
                "--question",
                f"--title={title}",
                f"--text={prompt}",
                f"--timeout={timeout_sec}",
                "--ok-label=Allow",
                "--cancel-label=Deny",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        # zenity: 0=OK, 1=cancel, 5=timeout
        if result.returncode == 0:
            return OverrideDecision.ALLOW
        if result.returncode in (1, 5):
            return OverrideDecision.DENY
        return OverrideDecision.UNAVAILABLE

    if shutil.which("kdialog"):
        result = subprocess.run(
            [
                "kdialog",
                "--yesno",
                prompt,
                "--title",
                title,
                "--yes-label",
                "Allow",
                "--no-label",
                "Deny",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
        if result.returncode == 0:
            return OverrideDecision.ALLOW
        if result.returncode == 1:
            return OverrideDecision.DENY
        return OverrideDecision.UNAVAILABLE

    print(_LINUX_UNAVAILABLE_HINT, file=sys.stderr)
    return OverrideDecision.UNAVAILABLE


def _macos_dialog(title: str, message: str, timeout_sec: int) -> OverrideDecision:
    # Escape for AppleScript string literals.
    safe_title = title.replace("\\", "\\\\").replace('"', '\\"')
    safe_message = message.replace("\\", "\\\\").replace('"', '\\"')
    script = (
        f'display dialog "{safe_message}" with title "{safe_title}" '
        f'buttons {{"Deny", "Allow"}} default button "Deny" '
        f"giving up after {int(timeout_sec)}"
    )
    result = subprocess.run(
        ["osascript", "-e", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_sec + 5,
    )
    if result.returncode != 0:
        return OverrideDecision.DENY
    out = (result.stdout or "").lower()
    if "gave up:true" in out.replace(" ", ""):
        return OverrideDecision.DENY
    if "allow" in out:
        return OverrideDecision.ALLOW
    return OverrideDecision.DENY


def _windows_dialog(title: str, message: str, timeout_sec: int) -> OverrideDecision:
    # MessageBox Yes/No; Yes = Allow. No native timeout without extra UI.
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$r = [System.Windows.Forms.MessageBox]::Show("
        f"@'\n{message}\n\nAllow this action anyway?\n'@, "
        f"'{title.replace(chr(39), chr(39)+chr(39))}', "
        "'YesNo', 'Warning'); "
        "if ($r -eq 'Yes') { exit 0 } else { exit 1 }"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_sec + 5,
    )
    if result.returncode == 0:
        return OverrideDecision.ALLOW
    if result.returncode == 1:
        return OverrideDecision.DENY
    return OverrideDecision.UNAVAILABLE
