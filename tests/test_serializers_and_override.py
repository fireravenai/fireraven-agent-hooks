"""Unit tests for serializers and human-override helpers."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.human_override import OverrideDecision, request_human_override
from core.serializers import (
    infer_claude_event,
    serialize_claude,
    serialize_cursor,
)


class SerializeCursorTests(unittest.TestCase):
    def test_before_read_file_includes_content(self) -> None:
        text = serialize_cursor(
            "beforeReadFile",
            {"file_path": "/tmp/a.py", "content": "print(1)\n"},
        )
        self.assertIsNotNone(text)
        assert text is not None
        self.assertIn("File read request: /tmp/a.py", text)
        self.assertIn("print(1)", text)

    def test_before_read_file_local_block(self) -> None:
        text = serialize_cursor("beforeReadFile", {"file_path": "/proj/.env"})
        self.assertTrue(text and text.startswith("__LOCAL_BLOCK__:"))

    def test_subagent_start(self) -> None:
        text = serialize_cursor(
            "subagentStart",
            {"task": "explore the auth module", "subagent_type": "explore"},
        )
        self.assertEqual(text, "Subagent start (explore):\nexplore the auth module")

    def test_after_file_edit(self) -> None:
        text = serialize_cursor(
            "afterFileEdit",
            {
                "file_path": "/tmp/a.py",
                "edits": [{"old_string": "a", "new_string": "b"}],
            },
        )
        self.assertIsNotNone(text)
        assert text is not None
        self.assertIn("Applied file edit: /tmp/a.py", text)
        self.assertIn("--- old ---", text)
        self.assertIn("b", text)

    def test_pre_tool_use_write(self) -> None:
        text = serialize_cursor(
            "preToolUse",
            {"tool_name": "Write", "tool_input": {"path": "x.py", "contents": "hi"}},
        )
        self.assertIn("Tool use: Write", text or "")


class SerializeClaudeTests(unittest.TestCase):
    def test_infer_events(self) -> None:
        self.assertEqual(
            infer_claude_event({"hook_event_name": "PostToolUse", "tool_name": "Read"}),
            "PostToolUse",
        )
        self.assertEqual(
            infer_claude_event({"tool_name": "Bash", "tool_input": {"command": "ls"}}),
            "PreToolUse",
        )
        self.assertEqual(
            infer_claude_event({"prompt": "hello"}),
            "UserPromptSubmit",
        )

    def test_post_tool_use_read_body(self) -> None:
        text = serialize_claude(
            {
                "hook_event_name": "PostToolUse",
                "tool_name": "Read",
                "tool_response": "secret stuff",
            }
        )
        self.assertEqual(text, "Claude PostToolUse (Read):\nsecret stuff")

    def test_pre_tool_use_unchanged(self) -> None:
        text = serialize_claude(
            {"tool_name": "Bash", "tool_input": {"command": "echo hi"}}
        )
        self.assertIn("Claude tool: Bash", text or "")


class HumanOverrideTests(unittest.TestCase):
    def test_linux_unavailable_without_display(self) -> None:
        with mock.patch.dict("os.environ", {"DISPLAY": "", "WAYLAND_DISPLAY": ""}, clear=False):
            # Clear display vars explicitly.
            env = {k: v for k, v in __import__("os").environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY")}
            with mock.patch.dict("os.environ", env, clear=True):
                with mock.patch("core.human_override.platform.system", return_value="Linux"):
                    decision = request_human_override("t", "m")
        self.assertEqual(decision, OverrideDecision.UNAVAILABLE)

    def test_zenity_allow(self) -> None:
        with mock.patch.dict("os.environ", {"DISPLAY": ":0"}, clear=False):
            with mock.patch("core.human_override.platform.system", return_value="Linux"):
                with mock.patch("core.human_override.shutil.which", side_effect=lambda c: c == "zenity"):
                    with mock.patch(
                        "core.human_override.subprocess.run",
                        return_value=mock.Mock(returncode=0),
                    ):
                        decision = request_human_override("t", "blocked")
        self.assertEqual(decision, OverrideDecision.ALLOW)


class CursorAdapterOverrideTests(unittest.TestCase):
    def test_policy_block_prompts_dialog_then_allows(self) -> None:
        from adapters import cursor as cursor_adapter

        payload = {
            "hook_event_name": "beforeShellExecution",
            "conversation_id": "s1",
            "command": "rm -rf /",
        }
        with mock.patch.object(cursor_adapter, "read_hook_input", return_value=payload):
            with mock.patch.object(cursor_adapter, "load_config", return_value={}):
                with mock.patch.object(
                    cursor_adapter,
                    "resolve_settings",
                    return_value={"fail_closed": False},
                ):
                    with mock.patch.object(
                        cursor_adapter,
                        "run_input_check",
                        side_effect=cursor_adapter.GuardrailError("blocked by policy"),
                    ):
                        with mock.patch.object(
                            cursor_adapter,
                            "request_human_override",
                            return_value=OverrideDecision.ALLOW,
                        ) as ask:
                            with self.assertRaises(SystemExit) as cm:
                                cursor_adapter.main()
        self.assertEqual(cm.exception.code, 0)
        ask.assert_called_once()

    def test_local_block_skips_dialog(self) -> None:
        from adapters import cursor as cursor_adapter

        payload = {
            "hook_event_name": "beforeReadFile",
            "conversation_id": "s1",
            "file_path": "/tmp/.env",
        }
        with mock.patch.object(cursor_adapter, "read_hook_input", return_value=payload):
            with mock.patch.object(cursor_adapter, "load_config", return_value={}):
                with mock.patch.object(
                    cursor_adapter,
                    "resolve_settings",
                    return_value={"fail_closed": True},
                ):
                    with mock.patch.object(
                        cursor_adapter,
                        "request_human_override",
                    ) as ask:
                        with self.assertRaises(SystemExit) as cm:
                            cursor_adapter.main()
        self.assertEqual(cm.exception.code, 0)
        ask.assert_not_called()


class ClaudeAdapterAskTests(unittest.TestCase):
    def test_pretool_policy_returns_ask_json(self) -> None:
        from adapters import claude as claude_adapter
        from core.guardrail import GuardrailError

        payload = {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "Bash",
            "tool_input": {"command": "evil"},
        }
        stdin = mock.Mock()
        stdin.read.return_value = json.dumps(payload)
        with mock.patch.object(claude_adapter.sys, "stdin", stdin):
            with mock.patch.object(claude_adapter, "load_config", return_value={}):
                with mock.patch.object(
                    claude_adapter,
                    "resolve_settings",
                    return_value={"fail_closed": False},
                ):
                    with mock.patch.object(
                        claude_adapter,
                        "run_input_check",
                        side_effect=GuardrailError("blocked by policy"),
                    ):
                        with mock.patch("builtins.print") as printer:
                            with self.assertRaises(SystemExit) as cm:
                                claude_adapter.main()
        self.assertEqual(cm.exception.code, 0)
        printed = None
        for call in printer.call_args_list:
            args = call.args
            if args and isinstance(args[0], str) and args[0].startswith("{"):
                printed = json.loads(args[0])
                break
        self.assertIsNotNone(printed)
        assert printed is not None
        self.assertEqual(
            printed["hookSpecificOutput"]["permissionDecision"],
            "ask",
        )

    def test_user_prompt_still_exits_2(self) -> None:
        from adapters import claude as claude_adapter
        from core.guardrail import GuardrailError

        payload = {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "s1",
            "prompt": "jailbreak",
        }
        stdin = mock.Mock()
        stdin.read.return_value = json.dumps(payload)
        with mock.patch.object(claude_adapter.sys, "stdin", stdin):
            with mock.patch.object(claude_adapter, "load_config", return_value={}):
                with mock.patch.object(
                    claude_adapter,
                    "resolve_settings",
                    return_value={"fail_closed": False},
                ):
                    with mock.patch.object(
                        claude_adapter,
                        "run_input_check",
                        side_effect=GuardrailError("blocked by policy"),
                    ):
                        with self.assertRaises(SystemExit) as cm:
                            claude_adapter.main()
        self.assertEqual(cm.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
