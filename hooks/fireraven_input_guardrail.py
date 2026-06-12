#!/usr/bin/env python3
"""
Windsurf Cascade pre_user_prompt hook: Fireraven FireGuard input guardrail.

Reads hook JSON from stdin, ensures a FireGuard conversation for the Cascade
trajectory, checks the user prompt via input_guardrails, and blocks (exit 2)
when unsafe or when the API is unreachable (fail-closed).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent / "config.env"
DEFAULT_API_URL = "https://api.fireraven.ai"
DEFAULT_EXECUTION_MODE = "fast"
DEFAULT_TIMEOUT_SEC = 15


def load_config() -> dict[str, str]:
    config: dict[str, str] = {}
    if not CONFIG_PATH.is_file():
        return config

    for line in CONFIG_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        config[key.strip()] = value.strip()
    return config


def block(message: str) -> None:
    print(message, file=sys.stderr)
    sys.exit(2)


def api_request(
    method: str,
    url: str,
    api_key: str,
    body: dict | None,
    timeout_sec: float,
) -> dict:
    data = None
    headers = {
        "X-Api-Key": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            payload = response.read().decode("utf-8")
            return json.loads(payload) if payload else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Request failed: {exc.reason}") from exc
    except TimeoutError as exc:
        raise RuntimeError(f"Request timed out after {timeout_sec}s") from exc


def ensure_conversation(
    api_url: str,
    api_key: str,
    project_id: str,
    trajectory_id: str,
    timeout_sec: float,
) -> str:
    query = urllib.parse.urlencode(
        {
            "project_id": project_id,
            "conversation_copilot_id": trajectory_id,
        }
    )
    url = f"{api_url.rstrip('/')}/public/fireguard/v1/conversation_copilot?{query}"
    result = api_request(
        "POST",
        url,
        api_key,
        {"name": f"Windsurf Cascade {trajectory_id}", "description": "Cascade hook session"},
        timeout_sec,
    )
    conversation_id = result.get("id")
    if not conversation_id:
        raise RuntimeError("conversation_copilot did not return a conversation id")
    return conversation_id


def check_input_guardrail(
    api_url: str,
    api_key: str,
    conversation_id: str,
    user_prompt: str,
    execution_mode: str,
    timeout_sec: float,
) -> dict:
    query = urllib.parse.urlencode({"conversation_id": conversation_id})
    url = f"{api_url.rstrip('/')}/public/fireguard/v1/input_guardrails?{query}"
    body = {
        "messages_history": [{"role": "user", "content": user_prompt}],
        "execution_mode": execution_mode,
    }
    return api_request("POST", url, api_key, body, timeout_sec)


def violation_message(result: dict) -> str:
    security = result.get("security_guardrail_results") or {}
    if security.get("is_safe") is False:
        message = security.get("security_violation_message")
        if message:
            return str(message)

    policies = (result.get("policies_guardrail_results") or {}).get("policies") or []
    for policy in policies:
        if policy.get("is_safe") is False:
            message = policy.get("policy_violation_message")
            if message:
                return str(message)

    return "Prompt blocked by Fireraven FireGuard."


def main() -> None:
    try:
        hook_input = json.loads(sys.stdin.read())
    except json.JSONDecodeError as exc:
        block(f"Fireraven guardrail hook: invalid hook input JSON ({exc}).")

    if hook_input.get("agent_action_name") != "pre_user_prompt":
        sys.exit(0)

    tool_info = hook_input.get("tool_info") or {}
    user_prompt = (tool_info.get("user_prompt") or "").strip()
    if not user_prompt:
        sys.exit(0)

    trajectory_id = hook_input.get("trajectory_id")
    if not trajectory_id:
        block("Fireraven guardrail hook: missing trajectory_id.")

    config = load_config()
    api_key = config.get("FIRERAVEN_GUARDRAILS_API_KEY") or os.environ.get("FIRERAVEN_GUARDRAILS_API_KEY", "")
    project_id = config.get("FIRERAVEN_PROJECT_ID") or os.environ.get("FIRERAVEN_PROJECT_ID", "")
    api_url = config.get("FIRERAVEN_API_URL") or os.environ.get("FIRERAVEN_API_URL", DEFAULT_API_URL)
    execution_mode = (
        config.get("FIRERAVEN_EXECUTION_MODE")
        or os.environ.get("FIRERAVEN_EXECUTION_MODE", DEFAULT_EXECUTION_MODE)
    )
    timeout_raw = (
        config.get("FIRERAVEN_REQUEST_TIMEOUT_SEC")
        or os.environ.get("FIRERAVEN_REQUEST_TIMEOUT_SEC", str(DEFAULT_TIMEOUT_SEC))
    )

    if not api_key:
        block("Fireraven guardrail hook: FIRERAVEN_GUARDRAILS_API_KEY is not configured.")
    if not project_id:
        block("Fireraven guardrail hook: FIRERAVEN_PROJECT_ID is not configured.")

    try:
        timeout_sec = float(timeout_raw)
    except ValueError:
        block("Fireraven guardrail hook: FIRERAVEN_REQUEST_TIMEOUT_SEC must be a number.")

    try:
        conversation_id = ensure_conversation(
            api_url, api_key, project_id, trajectory_id, timeout_sec
        )
        result = check_input_guardrail(
            api_url, api_key, conversation_id, user_prompt, execution_mode, timeout_sec
        )
    except RuntimeError as exc:
        block(f"Fireraven guardrail hook: {exc}")
    except json.JSONDecodeError as exc:
        block(f"Fireraven guardrail hook: invalid API response JSON ({exc}).")

    if result.get("is_safe") is True:
        sys.exit(0)

    block(violation_message(result))


if __name__ == "__main__":
    main()
