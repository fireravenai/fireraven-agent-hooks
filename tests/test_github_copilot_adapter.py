"""Tests for GitHub Copilot adapter and serializers."""

from __future__ import annotations

import json
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest import mock
from unittest.mock import patch

from adapters import github_copilot
from core.secured_notice import SECURED_MESSAGE
from core.serializers import serialize_github_copilot
from core.unavailable_notice import UNAVAILABLE_MESSAGE


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


class GitHubCopilotOverrideTests(unittest.TestCase):
    def test_pretool_dialog_allow(self) -> None:
        from core.guardrail import GuardrailError
        from core.human_override import OverrideDecision

        payload = {
            "hook_event_name": "preToolUse",
            "sessionId": "s1",
            "toolName": "bash",
            "toolArgs": {"command": "evil"},
        }
        with patch.object(github_copilot, "read_hook_input", return_value=payload):
            with patch.object(github_copilot, "load_config", return_value={}):
                with patch.object(
                    github_copilot,
                    "resolve_settings",
                    return_value={"fail_closed": False},
                ):
                    with patch.object(
                        github_copilot,
                        "run_input_check",
                        side_effect=GuardrailError("blocked by policy"),
                    ):
                        with patch.object(
                            github_copilot,
                            "resolve_override",
                            return_value=OverrideDecision.ALLOW,
                        ) as ask:
                            with self.assertRaises(SystemExit) as cm:
                                github_copilot.main()
        self.assertEqual(cm.exception.code, 0)
        ask.assert_called_once()

    def test_pretool_dialog_deny(self) -> None:
        from core.guardrail import GuardrailError
        from core.human_override import OverrideDecision

        payload = {
            "hook_event_name": "preToolUse",
            "sessionId": "s1",
            "toolName": "bash",
            "toolArgs": {"command": "evil"},
        }
        with patch.object(github_copilot, "read_hook_input", return_value=payload):
            with patch.object(github_copilot, "load_config", return_value={}):
                with patch.object(
                    github_copilot,
                    "resolve_settings",
                    return_value={"fail_closed": False},
                ):
                    with patch.object(
                        github_copilot,
                        "run_input_check",
                        side_effect=GuardrailError("blocked by policy"),
                    ):
                        with patch.object(
                            github_copilot,
                            "resolve_override",
                            return_value=OverrideDecision.DENY,
                        ):
                            with patch("sys.stdout", new_callable=StringIO) as stdout:
                                with self.assertRaises(SystemExit) as cm:
                                    github_copilot.main()
        self.assertEqual(cm.exception.code, 0)
        data = json.loads(stdout.getvalue())
        self.assertEqual(data["permissionDecision"], "deny")

    def test_local_block_skips_dialog(self) -> None:
        from core.guardrail import GuardrailError

        payload = {
            "hook_event_name": "preToolUse",
            "sessionId": "s1",
            "toolName": "view",
            "toolArgs": {"path": "/tmp/.env"},
        }
        with patch.object(github_copilot, "read_hook_input", return_value=payload):
            with patch.object(github_copilot, "load_config", return_value={}):
                with patch.object(
                    github_copilot,
                    "resolve_settings",
                    return_value={"fail_closed": True},
                ):
                    with patch.object(
                        github_copilot,
                        "run_input_check",
                        side_effect=GuardrailError(
                            "Access to sensitive path blocked locally: /tmp/.env",
                            overridable=False,
                        ),
                    ):
                        with patch(
                            "core.human_override.request_human_override",
                        ) as ask:
                            with patch("sys.stdout", new_callable=StringIO):
                                with self.assertRaises(SystemExit) as cm:
                                    github_copilot.main()
        self.assertEqual(cm.exception.code, 0)
        ask.assert_not_called()


class GitHubCopilotPromptTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        patcher = mock.patch(
            "core.session_store.hooks_root",
            return_value=Path(self._tmpdir.name),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run(
        self,
        *,
        session_id: str = "gh-prompt",
        fail_closed: bool = False,
        side_effect: Exception | None = None,
        secured_toast: mock.MagicMock | None = None,
    ) -> str:
        payload = {
            "hook_event_name": "UserPromptSubmit",
            "session_id": session_id,
            "prompt": "My phone number is +1456 78 78 78 78",
        }
        check_kw: dict = {}
        if side_effect is not None:
            check_kw["side_effect"] = side_effect
        else:
            check_kw["return_value"] = {"is_safe": True}
        with patch.object(github_copilot, "read_hook_input", return_value=payload):
            with patch.object(github_copilot, "load_config", return_value={}):
                with patch.object(
                    github_copilot,
                    "resolve_settings",
                    return_value={"fail_closed": fail_closed},
                ):
                    with patch.object(github_copilot, "run_input_check", **check_kw):
                        with patch(
                            "core.secured_notice.show_unavailable_toast",
                            secured_toast if secured_toast is not None else mock.DEFAULT,
                        ):
                            with patch("core.unavailable_notice.show_unavailable_toast"):
                                with patch("sys.stdout", new_callable=StringIO) as stdout:
                                    with self.assertRaises(SystemExit) as cm:
                                        github_copilot.main()
        self.assertEqual(cm.exception.code, 0)
        return stdout.getvalue()

    def test_prompt_guardrail_blocks_without_override(self) -> None:
        from core.guardrail import GuardrailError

        with patch.object(github_copilot, "resolve_override") as ask:
            raw = self._run(side_effect=GuardrailError("PII detected", overridable=False))
        ask.assert_not_called()
        data = json.loads(raw)
        self.assertEqual(data["decision"], "block")
        self.assertEqual(data["reason"], "PII detected")

    def test_first_success_emits_secured_notice_once(self) -> None:
        toast = mock.MagicMock()
        first = self._run(secured_toast=toast)
        second = self._run(secured_toast=toast)
        self.assertEqual(json.loads(first)["systemMessage"], SECURED_MESSAGE)
        self.assertEqual(second, "")
        toast.assert_called_once_with(SECURED_MESSAGE)

    def test_fail_open_emits_unavailable_not_secured(self) -> None:
        raw = self._run(side_effect=RuntimeError("HTTP 503"))
        data = json.loads(raw)
        self.assertEqual(data["systemMessage"], UNAVAILABLE_MESSAGE)
        self.assertNotEqual(data["systemMessage"], SECURED_MESSAGE)

    def test_fail_closed_prompt_blocks(self) -> None:
        raw = self._run(fail_closed=True, side_effect=RuntimeError("HTTP 503"))
        data = json.loads(raw)
        self.assertEqual(data["decision"], "block")
        self.assertIn("HTTP 503", data["reason"])


if __name__ == "__main__":
    unittest.main()
