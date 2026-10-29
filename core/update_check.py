"""Notify-before-apply update checks for Fireraven agent hooks.

Never raises into the hook path. Soft-fails on network/dialog/install errors.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from core.config import get_setting, hooks_root, load_config
from core.unavailable_notice import show_unavailable_toast

DEFAULT_GITHUB_REPO = "fireravenai/fireraven-agent-hooks"
DEFAULT_GITHUB_REF = "main"
DEFAULT_GITLAB_HOST = "https://gitlab.com"
DEFAULT_GITLAB_REF = "dev"
GITHUB_INTERVAL_SEC = 21600  # 6 hours
GITLAB_INTERVAL_SEC = 300  # 5 minutes
UPDATE_DIALOG_TIMEOUT_SEC = 120
FETCH_TIMEOUT_SEC = 10

_STATE_NAME = ".update_state.json"
_META_NAME = "install_meta.json"
_VERSION_NAME = "VERSION"
_UPDATE_LOG_NAME = "update.log"
_GITLAB_RAW_RE = re.compile(r"^(https?://[^/]+)/(.+)/-/raw/([^/]+)$")


def maybe_prompt_update() -> None:
    """Entry point from bootstrap. Never raises."""
    try:
        _maybe_prompt_update()
    except Exception:
        return


def parse_gitlab_raw_base(raw: str) -> dict[str, str] | None:
    m = _GITLAB_RAW_RE.match((raw or "").rstrip("/"))
    if not m:
        return None
    return {
        "gitlab_host": m.group(1),
        "project": m.group(2),
        "ref": m.group(3),
    }


def resolve_channel(
    meta: dict[str, Any] | None = None,
    *,
    env: dict[str, str] | None = None,
) -> dict[str, str]:
    """Return channel info: channel, raw_base, gitlab_host, project, ref."""
    environ = env if env is not None else os.environ
    meta = meta or {}

    meta_channel = str(meta.get("channel") or "").strip()
    if meta_channel == "gitlab_api" or (meta.get("project") and meta.get("gitlab_host")):
        return {
            "channel": "gitlab_api",
            "raw_base": "",
            "gitlab_host": str(meta.get("gitlab_host") or DEFAULT_GITLAB_HOST).rstrip("/"),
            "project": str(meta.get("project") or "").strip(),
            "ref": str(meta.get("ref") or DEFAULT_GITLAB_REF).strip() or DEFAULT_GITLAB_REF,
        }

    project = (environ.get("FIRERAVEN_HOOKS_GITLAB_PROJECT") or "").strip()
    if project:
        return {
            "channel": "gitlab_api",
            "raw_base": "",
            "gitlab_host": (
                environ.get("FIRERAVEN_HOOKS_GITLAB_HOST") or DEFAULT_GITLAB_HOST
            )
            .strip()
            .rstrip("/"),
            "project": project,
            "ref": (environ.get("FIRERAVEN_HOOKS_REF") or DEFAULT_GITLAB_REF).strip()
            or DEFAULT_GITLAB_REF,
        }

    raw = ""
    if meta.get("raw_base"):
        raw = str(meta.get("raw_base") or "").strip().rstrip("/")
    if not raw:
        raw = (environ.get("FIRERAVEN_HOOKS_RAW_BASE") or "").strip().rstrip("/")
    if raw:
        parsed = parse_gitlab_raw_base(raw)
        if parsed:
            return {
                "channel": "gitlab_api",
                "raw_base": "",
                "gitlab_host": parsed["gitlab_host"],
                "project": parsed["project"],
                "ref": parsed["ref"],
            }
        return {
            "channel": "github",
            "raw_base": raw,
            "gitlab_host": "",
            "project": "",
            "ref": str(
                meta.get("ref") or environ.get("FIRERAVEN_HOOKS_REF") or DEFAULT_GITHUB_REF
            ),
        }

    repo = (environ.get("FIRERAVEN_HOOKS_REPO") or DEFAULT_GITHUB_REPO).strip()
    ref = (environ.get("FIRERAVEN_HOOKS_REF") or DEFAULT_GITHUB_REF).strip()
    if meta:
        repo = str(meta.get("repo") or repo).strip() or repo
        ref = str(meta.get("ref") or ref).strip() or ref
    return {
        "channel": "github",
        "raw_base": f"https://raw.githubusercontent.com/{repo}/refs/heads/{ref}",
        "gitlab_host": "",
        "project": "",
        "ref": ref,
    }


def file_url(channel: dict[str, str], path: str) -> str:
    if channel.get("channel") == "gitlab_api":
        host = channel["gitlab_host"].rstrip("/")
        project = urllib.parse.quote(channel["project"], safe="")
        enc_path = urllib.parse.quote(path, safe="")
        ref = urllib.parse.quote(channel["ref"], safe="")
        return f"{host}/api/v4/projects/{project}/repository/files/{enc_path}/raw?ref={ref}"
    return f"{channel['raw_base'].rstrip('/')}/{path}"


def resolve_raw_base(
    meta: dict[str, Any] | None = None,
    *,
    env: dict[str, str] | None = None,
) -> str:
    """Compat: GitHub raw base, or GitLab host when channel is gitlab_api."""
    ch = resolve_channel(meta, env=env)
    if ch["channel"] == "gitlab_api":
        return ch["gitlab_host"]
    return ch["raw_base"]


def resolve_check_interval_sec(
    channel_or_raw: str | dict[str, str],
    *,
    env: dict[str, str] | None = None,
    config: dict[str, str] | None = None,
) -> int:
    """Env override, else GitLab 5m / GitHub 6h."""
    environ = env if env is not None else os.environ
    cfg = config if config is not None else {}
    override = get_setting(cfg, "FIRERAVEN_UPDATE_CHECK_INTERVAL_SEC", "")
    if not override:
        override = (environ.get("FIRERAVEN_UPDATE_CHECK_INTERVAL_SEC") or "").strip()
    if override:
        try:
            return max(0, int(override))
        except ValueError:
            pass
    if isinstance(channel_or_raw, dict):
        if channel_or_raw.get("channel") == "gitlab_api":
            return GITLAB_INTERVAL_SEC
        raw = channel_or_raw.get("raw_base") or channel_or_raw.get("gitlab_host") or ""
    else:
        raw = channel_or_raw
    if "gitlab" in (raw or "").lower():
        return GITLAB_INTERVAL_SEC
    return GITHUB_INTERVAL_SEC


def parse_semver(version: str) -> tuple[int, ...] | None:
    text = (version or "").strip().lstrip("vV")
    if not text:
        return None
    parts: list[int] = []
    for chunk in text.split("."):
        num = ""
        for ch in chunk:
            if ch.isdigit():
                num += ch
            else:
                break
        if not num:
            return None
        parts.append(int(num))
    return tuple(parts) if parts else None


def is_newer(remote: str, local: str) -> bool:
    remote_t = parse_semver(remote)
    local_t = parse_semver(local)
    if remote_t is None or local_t is None:
        return False
    n = max(len(remote_t), len(local_t))
    remote_p = remote_t + (0,) * (n - len(remote_t))
    local_p = local_t + (0,) * (n - len(local_t))
    return remote_p > local_p


def resolve_hooks_token(
    *,
    config: dict[str, str] | None = None,
    env: dict[str, str] | None = None,
) -> str:
    cfg = config if config is not None else {}
    environ = env if env is not None else os.environ
    return get_setting(cfg, "FIRERAVEN_HOOKS_TOKEN", "").strip() or (
        environ.get("FIRERAVEN_HOOKS_TOKEN") or ""
    ).strip()


def _maybe_prompt_update() -> None:
    config = load_config()
    if _updates_disabled(config):
        return

    root = hooks_root()
    meta = _read_json(root / _META_NAME)
    channel = resolve_channel(meta)
    state = _read_json(root / _STATE_NAME)
    interval = resolve_check_interval_sec(channel, config=config)
    now = int(time.time())
    last_check = int(state.get("last_check_unix") or 0)
    if interval > 0 and last_check and (now - last_check) < interval:
        return

    local_version = _read_version(root / _VERSION_NAME)
    if not local_version:
        _write_state(root, last_check_unix=now, snoozed_version=state.get("snoozed_version"))
        return

    if channel["channel"] == "gitlab_api" and not resolve_hooks_token(config=config):
        _write_state(root, last_check_unix=now, snoozed_version=state.get("snoozed_version"))
        return

    remote_version = _fetch_remote_version(channel, config=config)
    _write_state(root, last_check_unix=now, snoozed_version=state.get("snoozed_version"))
    if not remote_version or not is_newer(remote_version, local_version):
        return

    snoozed = str(state.get("snoozed_version") or "").strip()
    if snoozed and snoozed == remote_version.strip():
        return

    show_unavailable_toast(
        f"Fireraven hooks update available: {local_version} → {remote_version}"
    )
    decision = request_update_dialog(
        title="Fireraven Agent Hooks",
        message=(
            f"A new version of Fireraven agent hooks is available.\n\n"
            f"Installed: {local_version}\n"
            f"Available: {remote_version}\n\n"
            f"Apply the update now?"
        ),
    )
    if decision == "later":
        _write_state(root, last_check_unix=now, snoozed_version=remote_version.strip())
        return
    if decision != "allow":
        return

    agents = str((meta or {}).get("agents") or "windsurf").strip() or "windsurf"
    remote = remote_version.strip()
    log_path = _update_log_path(root)
    show_unavailable_toast(f"Updating Fireraven hooks to {remote}…")
    ok = _apply_update(
        channel, agents, config=config, expected_version=remote, root=root
    )
    if ok:
        _write_state(root, last_check_unix=now, snoozed_version=None)
        show_unavailable_toast(f"Fireraven hooks updated to {remote}")
    else:
        show_unavailable_toast(f"Fireraven hooks update failed — see {log_path}")


def _updates_disabled(config: dict[str, str]) -> bool:
    raw = get_setting(config, "FIRERAVEN_UPDATE_CHECK", "1").strip().lower()
    return raw in {"0", "false", "no", "off"}


def _read_version(path: Path) -> str:
    try:
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8").strip().splitlines()[0].strip()
    except OSError:
        return ""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if not path.is_file():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_state(root: Path, *, last_check_unix: int, snoozed_version: Any = None) -> None:
    payload: dict[str, Any] = {"last_check_unix": int(last_check_unix)}
    if snoozed_version:
        payload["snoozed_version"] = str(snoozed_version)
    path = root / _STATE_NAME
    try:
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except OSError:
        return


def _http_get(url: str, *, token: str = "") -> str:
    headers = {"User-Agent": "fireraven-agent-hooks"}
    if token:
        headers["PRIVATE-TOKEN"] = token
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SEC) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _fetch_remote_version(channel: dict[str, str], *, config: dict[str, str]) -> str:
    url = file_url(channel, _VERSION_NAME)
    token = ""
    if channel.get("channel") == "gitlab_api":
        token = resolve_hooks_token(config=config)
        if not token:
            return ""
    try:
        body = _http_get(url, token=token)
        return body.strip().splitlines()[0].strip()
    except (urllib.error.URLError, TimeoutError, OSError, IndexError, ValueError):
        return ""


def request_update_dialog(
    *,
    title: str,
    message: str,
    timeout_sec: int = UPDATE_DIALOG_TIMEOUT_SEC,
) -> str:
    """Return 'allow', 'later', or 'unavailable'. Never raises."""
    try:
        system = platform.system()
        if system == "Darwin":
            return _macos_update_dialog(title, message, timeout_sec)
        if system == "Windows":
            return _windows_update_dialog(title, message, timeout_sec)
        return _linux_update_dialog(title, message, timeout_sec)
    except Exception:
        return "later"


def _linux_update_dialog(title: str, message: str, timeout_sec: int) -> str:
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return "unavailable"

    if shutil.which("yad"):
        result = subprocess.run(
            [
                "yad",
                f"--title={title}",
                f"--text={message}",
                "--text-align=left",
                "--window-icon=",
                "--button=Allow:0",
                "--button=Later:1",
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
        return "allow" if result.returncode == 0 else "later"

    if shutil.which("zenity"):
        result = subprocess.run(
            [
                "zenity",
                "--question",
                f"--title={title}",
                f"--text={message}",
                f"--timeout={timeout_sec}",
                "--ok-label=Allow",
                "--cancel-label=Later",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        return "allow" if result.returncode == 0 else "later"

    if shutil.which("kdialog"):
        try:
            result = subprocess.run(
                [
                    "kdialog",
                    "--yesno",
                    message,
                    "--title",
                    title,
                    "--yes-label",
                    "Allow",
                    "--no-label",
                    "Later",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
        except subprocess.TimeoutExpired:
            return "later"
        return "allow" if result.returncode == 0 else "later"

    return "unavailable"


def _macos_update_dialog(title: str, message: str, timeout_sec: int) -> str:
    safe_title = title.replace("\\", "\\\\").replace('"', '\\"')
    safe_message = message.replace("\\", "\\\\").replace('"', '\\"')
    script = (
        f'display dialog "{safe_message}" with title "{safe_title}" '
        f'buttons {{"Later", "Allow"}} default button "Later" '
        f"giving up after {int(timeout_sec)}"
    )
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_sec + 5,
        )
    except subprocess.TimeoutExpired:
        return "later"
    if result.returncode != 0:
        return "later"
    out = (result.stdout or "").lower()
    if "gave up:true" in out.replace(" ", ""):
        return "later"
    if "allow" in out:
        return "allow"
    return "later"


def _windows_update_dialog(title: str, message: str, timeout_sec: int) -> str:
    safe_title = title.replace("'", "''")
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$r = [System.Windows.Forms.MessageBox]::Show("
        f"@'\n{message}\n'@, "
        f"'{safe_title}', "
        "'YesNo', 'Information'); "
        "if ($r -eq 'Yes') { exit 0 } else { exit 1 }"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_sec + 5,
        )
    except subprocess.TimeoutExpired:
        return "later"
    return "allow" if result.returncode == 0 else "later"


def _apply_env(channel: dict[str, str], config: dict[str, str]) -> dict[str, str]:
    env = os.environ.copy()
    if channel.get("channel") == "gitlab_api":
        env["FIRERAVEN_HOOKS_GITLAB_PROJECT"] = channel["project"]
        env["FIRERAVEN_HOOKS_GITLAB_HOST"] = channel["gitlab_host"]
        env["FIRERAVEN_HOOKS_REF"] = channel["ref"]
        token = resolve_hooks_token(config=config)
        if token:
            env["FIRERAVEN_HOOKS_TOKEN"] = token
        env.pop("FIRERAVEN_HOOKS_RAW_BASE", None)
    else:
        env["FIRERAVEN_HOOKS_RAW_BASE"] = channel["raw_base"]
    return env


def _update_log_path(root: Path | None = None) -> Path:
    base = root if root is not None else hooks_root()
    state = base / "state"
    state.mkdir(parents=True, exist_ok=True)
    return state / _UPDATE_LOG_NAME


def _write_update_log(path: Path, text: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
    except OSError:
        return


def _run_install_command(cmd: list[str], *, env: dict[str, str], log_path: Path) -> int:
    try:
        result = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=300,
            env=env,
        )
        chunks = [result.stdout or "", result.stderr or ""]
        body = "".join(chunks).strip()
        if not body:
            body = f"(no output, exit {result.returncode})"
        _write_update_log(log_path, body)
        return int(result.returncode)
    except Exception as exc:
        _write_update_log(log_path, f"update apply error: {exc}")
        return -1


def _apply_update(
    channel: dict[str, str],
    agents: str,
    *,
    config: dict[str, str],
    expected_version: str,
    root: Path | None = None,
) -> bool:
    """Run remote installer. Return True only if exit 0 and VERSION matches expected."""
    hooks = root if root is not None else hooks_root()
    log_path = _update_log_path(hooks)
    expected = (expected_version or "").strip()
    system = platform.system()
    env = _apply_env(channel, config)
    try:
        if channel.get("channel") == "gitlab_api":
            install_path = "install.ps1" if system == "Windows" else "install.sh"
            url = file_url(channel, install_path)
            token = resolve_hooks_token(config=config)
            if not token:
                _write_update_log(log_path, "update apply error: missing FIRERAVEN_HOOKS_TOKEN")
                return False
            if system == "Windows":
                cmd_str = (
                    f"$h=@{{'PRIVATE-TOKEN'='{token}'}}; "
                    f"$s=(Invoke-WebRequest -UseBasicParsing -Headers $h -Uri '{url}').Content; "
                    f"& ([scriptblock]::Create($s)) -Agent {agents}"
                )
                rc = _run_install_command(
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd_str],
                    env=env,
                    log_path=log_path,
                )
            else:
                rc = _run_install_command(
                    [
                        "sh",
                        "-c",
                        f'curl -fsSL -H "PRIVATE-TOKEN: {token}" "{url}" | sh -s -- --agent {agents}',
                    ],
                    env=env,
                    log_path=log_path,
                )
        else:
            base = channel["raw_base"].rstrip("/")
            if system == "Windows":
                ps1_url = f"{base}/install.ps1"
                cmd_str = (
                    f"& ([scriptblock]::Create((irm '{ps1_url}'))) "
                    f"-Agent {agents}"
                )
                rc = _run_install_command(
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd_str],
                    env=env,
                    log_path=log_path,
                )
            else:
                install_url = f"{base}/install.sh"
                rc = _run_install_command(
                    ["sh", "-c", f'curl -fsSL "{install_url}" | sh -s -- --agent {agents}'],
                    env=env,
                    log_path=log_path,
                )
    except Exception as exc:
        _write_update_log(log_path, f"update apply error: {exc}")
        return False

    if rc != 0:
        return False
    installed = _read_version(hooks / _VERSION_NAME)
    return bool(expected) and installed == expected


def apply_command_preview(channel: dict[str, str], agents: str) -> str:
    """Test helper: Unix apply command preview."""
    if channel.get("channel") == "gitlab_api":
        url = file_url(channel, "install.sh")
        return (
            f'curl -fsSL -H "PRIVATE-TOKEN: $FIRERAVEN_HOOKS_TOKEN" "{url}" '
            f"| sh -s -- --agent {agents}"
        )
    base = channel["raw_base"].rstrip("/")
    return f'curl -fsSL "{base}/install.sh" | sh -s -- --agent {agents}'
