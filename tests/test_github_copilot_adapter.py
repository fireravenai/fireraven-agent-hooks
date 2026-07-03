"""Tests for GitHub Copilot adapter and serializers."""

from __future__ import annotations

import json
import unittest
from io import StringIO
from unittest.mock import patch

from adapters import github_copilot
from core.serializers import serialize_github_copilot


class SerializeGitHubCopilotTests(unittest.TestCase):
    def test_user_prompt_submitted(self) -> None:
        payload = {"sessionId": "s1", "prompt": "fix the auth bug"}
        text = serialize_github_copilot("userPromptSubmitted", payload)
        self.assertEqual(text, "fix the auth bug")

    def test_pre_tool_use_bash_json_string_args(self) -> None:
        payload = {
            "sessionId": "s1",
            "toolName": "bash",
            "toolArgs": json.dumps({"command": "npm test", "cwd": "/tmp"}),
        }
        text = serialize_github_copilot("preToolUse", payload)
        self.assertIn("npm test", text or "")
        self.assertIn("/tmp", text or "")

    def test_pre_tool_use_view(self) -> None:
        payload = {
            "sessionId": "s1",
            "toolName": "view",
            "toolArgs": {"path": "README.md"},
        }
        text = serialize_github_copilot("preToolUse", payload)
        self.assertIn("README.md", text or "")

    def test_pre_tool_use_edit(self) -> None:
        payload = {
            "sessionId": "s1",
            "toolName": "edit",
            "toolArgs": {
                "path": "src/main.py",
                "old_string": "foo",
                "new_string": "bar",
            },
        }
        text = serialize_github_copilot("preToolUse", payload)
        self.assertIn("src/main.py", text or "")
        self.assertIn("foo", text or "")
        self.assertIn("bar", text or "")

    def test_post_tool_use(self) -> None:
        payload = {
            "sessionId": "s1",
            "toolResult": {"textResultForLlm": "All tests passed"},
        }
        text = serialize_github_copilot("postToolUse", payload)
        self.assertEqual(text, "All tests passed")

    def test_pascal_case_pre_tool_use(self) -> None:
        payload = {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
        }
        text = serialize_github_copilot("preToolUse", payload)
        self.assertIn("ls", text or "")


class InferGitHubCopilotEventTests(unittest.TestCase):
    def test_camel_case_pre_tool_use(self) -> None:
        event = github_copilot.infer_github_copilot_event(
            {"toolName": "bash", "toolArgs": {"command": "ls"}}
        )
        self.assertEqual(event, "preToolUse")

    def test_pascal_case_user_prompt(self) -> None:
        event = github_copilot.infer_github_copilot_event(
            {"hook_event_name": "UserPromptSubmit", "prompt": "hi"}
        )
        self.assertEqual(event, "userPromptSubmitted")

    def test_post_tool_use(self) -> None:
        event = github_copilot.infer_github_copilot_event(
            {"toolName": "bash", "toolResult": {"textResultForLlm": "ok"}}
        )
        self.assertEqual(event, "postToolUse")


class GitHubCopilotAdapterOutputTests(unittest.TestCase):
    def test_deny_outputs_permission_decision(self) -> None:
        with patch("sys.stdout", new_callable=StringIO) as stdout:
            with self.assertRaises(SystemExit) as ctx:
                github_copilot._deny("blocked")
            self.assertEqual(ctx.exception.code, 0)
        data = json.loads(stdout.getvalue())
        self.assertEqual(data["permissionDecision"], "deny")
        self.assertEqual(data["permissionDecisionReason"], "blocked")

    def test_allow_exits_zero_without_output(self) -> None:
        with patch("sys.stdout", new_callable=StringIO) as stdout:
            with self.assertRaises(SystemExit) as ctx:
                github_copilot._allow()
            self.assertEqual(ctx.exception.code, 0)
        self.assertEqual(stdout.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
