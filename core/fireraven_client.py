from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request


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
    session_id: str,
    timeout_sec: float,
    label: str = "Agent session",
) -> str:
    query = urllib.parse.urlencode(
        {
            "project_id": project_id,
            "conversation_copilot_id": session_id,
        }
    )
    url = f"{api_url.rstrip('/')}/public/fireguard/v1/conversation_copilot?{query}"
    result = api_request(
        "POST",
        url,
        api_key,
        {"name": f"{label} {session_id}", "description": "Fireraven agent hook session"},
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
    messages_history: list[dict[str, str]],
    execution_mode: str,
    timeout_sec: float,
) -> dict:
    query = urllib.parse.urlencode({"conversation_id": conversation_id})
    url = f"{api_url.rstrip('/')}/public/fireguard/v1/input_guardrails?{query}"
    body = {
        "messages_history": messages_history,
        "execution_mode": execution_mode,
    }
    return api_request("POST", url, api_key, body, timeout_sec)


def check_output_guardrail(
    api_url: str,
    api_key: str,
    conversation_id: str,
    input_id: str,
    output: str,
    execution_mode: str,
    timeout_sec: float,
) -> dict:
    query = urllib.parse.urlencode({"conversation_id": conversation_id})
    url = f"{api_url.rstrip('/')}/public/fireguard/v1/output_guardrails?{query}"
    body = {
        "input_id": input_id,
        "output": output,
        "execution_mode": execution_mode,
    }
    return api_request("POST", url, api_key, body, timeout_sec)


def violation_message(result: dict, default: str = "Blocked by Fireraven FireGuard.") -> str:
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

    return default
