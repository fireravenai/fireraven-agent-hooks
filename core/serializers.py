from __future__ import annotations

import json
import re
from pathlib import Path

SENSITIVE_PATH_RE = re.compile(
    r"(\.env($|\.|/)|id_rsa|credentials|secret|\.pem$|token|api[_-]?key)",
    re.IGNORECASE,
)

WINDSURF_INPUT_EVENTS = {
    "pre_user_prompt",
    "pre_run_command",
    "pre_mcp_tool_use",
    "pre_write_code",
    "pre_read_code",
}

WINDSURF_OUTPUT_AUDIT_EVENTS = {
    "post_cascade_response",
    "post_write_code",
}

CURSOR_INPUT_EVENTS = {
    "beforeSubmitPrompt",
    "beforeShellExecution",
    "beforeMCPExecution",
    "beforeReadFile",
    "preToolUse",
}


def local_sensitive_path_block(file_path: str) -> str | None:
    if SENSITIVE_PATH_RE.search(file_path):
        return f"Access to sensitive path blocked locally: {file_path}"
    return None


def serialize_windsurf(action: str, tool_info: dict) -> str | None:
    if action == "pre_user_prompt":
        text = (tool_info.get("user_prompt") or "").strip()
        return text or None

    if action == "pre_run_command":
        command = (tool_info.get("command_line") or "").strip()
        cwd = (tool_info.get("cwd") or "").strip()
        if not command:
            return None
        return f"Shell command to execute:\n{command}\n\nWorking directory:\n{cwd}"

    if action == "pre_mcp_tool_use":
        server = tool_info.get("mcp_server_name") or ""
        tool = tool_info.get("mcp_tool_name") or ""
        args = tool_info.get("mcp_tool_arguments") or {}
        if not server and not tool:
            return None
        return (
            f"MCP tool call:\nServer: {server}\nTool: {tool}\n"
            f"Arguments:\n{json.dumps(args, indent=2)}"
        )

    if action == "pre_write_code":
        file_path = tool_info.get("file_path") or ""
        edits = tool_info.get("edits") or []
        if not file_path and not edits:
            return None
        parts = [f"File write request: {file_path}"]
        for edit in edits:
            old = edit.get("old_string") or ""
            new = edit.get("new_string") or ""
            parts.append(f"--- old ---\n{old}\n--- new ---\n{new}")
        return "\n\n".join(parts)

    if action == "pre_read_code":
        file_path = (tool_info.get("file_path") or "").strip()
        if not file_path:
            return None
        blocked = local_sensitive_path_block(file_path)
        if blocked:
            return f"__LOCAL_BLOCK__:{blocked}"
        snippet = ""
        path = Path(file_path)
        if path.is_file() and path.stat().st_size <= 32_000:
            try:
                snippet = path.read_text(encoding="utf-8", errors="replace")[:8_000]
            except OSError:
                snippet = ""
        if snippet:
            return f"File read request: {file_path}\n\nContent preview:\n{snippet}"
        return f"File read request: {file_path}"

    if action == "post_cascade_response":
        return (tool_info.get("response") or "").strip() or None

    if action == "post_write_code":
        file_path = tool_info.get("file_path") or ""
        edits = tool_info.get("edits") or []
        parts = [f"Applied file write: {file_path}"]
        for edit in edits:
            parts.append(edit.get("new_string") or "")
        text = "\n".join(parts).strip()
        return text or None

    return None


def serialize_cursor(hook_event: str, payload: dict) -> str | None:
    if hook_event == "beforeSubmitPrompt":
        return (payload.get("prompt") or payload.get("user_prompt") or "").strip() or None

    if hook_event == "beforeShellExecution":
        command = (payload.get("command") or "").strip()
        return f"Shell command to execute:\n{command}" if command else None

    if hook_event == "beforeMCPExecution":
        tool = payload.get("tool_name") or payload.get("mcp_tool_name") or ""
        args = payload.get("tool_input") or payload.get("mcp_tool_arguments") or {}
        return f"MCP call: {tool}\n{json.dumps(args, indent=2)}" if tool or args else None

    if hook_event == "beforeReadFile":
        file_path = (payload.get("file_path") or payload.get("path") or "").strip()
        if not file_path:
            return None
        blocked = local_sensitive_path_block(file_path)
        if blocked:
            return f"__LOCAL_BLOCK__:{blocked}"
        return f"File read request: {file_path}"

    if hook_event == "preToolUse":
        tool_name = payload.get("tool_name") or ""
        tool_input = payload.get("tool_input") or payload.get("input") or {}
        if not tool_name and not tool_input:
            return None
        return f"Tool use: {tool_name}\n{json.dumps(tool_input, indent=2)}"

    return None


def serialize_claude(payload: dict) -> str | None:
    tool_name = payload.get("tool_name") or payload.get("name") or ""
    tool_input = payload.get("tool_input") or payload.get("input") or payload.get("arguments") or {}
    if isinstance(tool_input, str):
        text = tool_input.strip()
        return text or None
    if tool_name or tool_input:
        return f"Claude tool: {tool_name}\n{json.dumps(tool_input, indent=2)}"
    prompt = (payload.get("prompt") or "").strip()
    return prompt or None
