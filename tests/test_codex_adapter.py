"""Tests for the Codex Desktop adapter."""

from __future__ import annotations

import json
import unittest
from io import StringIO
from unittest.mock import patch

from adapters import codex
from core.guardrail import FireguardUnavailableError, GuardrailError
from core.human_override import OverrideDecision
from core.secured_notice import SECURED_MESSAGE
from core.serializers import serialize_codex
from core.unavailable_notice import NOT_CONFIGURED_MESSAGE, UNAVAILABLE_MESSAGE


class SerializeCodexTests(unittest.TestCase):
    def test_user_prompt(self) -> None:
        text = serialize_codex({"hook_event_name": "UserPromptSubmit", "prompt": "hello"})
        self.assertEqual(text, "hello")

    def test_bash_tool_call(self) -> None:
        text = serialize_codex(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "ls"},
            }
        )
        self.assertIn("Codex tool: Bash", text or "")
        self.assertIn("ls", text or "")

    def test_local_block_on_command_path(self) -> None:
        text = serialize_codex(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "cat /tmp/.env"},
            }
        )
        self.assertTrue(text and text.startswith("__LOCAL_BLOCK__:"))

    def test_local_block_on_file_path(self) -> None:
        text = serialize_codex(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "apply_patch",
                "tool_input": {"file_path": "/tmp/id_rsa"},
            }
        )
        self.assertTrue(text and text.startswith("__LOCAL_BLOCK__:"))

    def test_post_tool_use(self) -> None:
        text = serialize_codex(
            {
                "hook_event_name": "PostToolUse",
                "tool_name": "Bash",
                "tool_response": "ok",
            }
        )
        self.assertIn("Codex PostToolUse (Bash)", text or "")
        self.assertIn("ok", text or "")


class CodexAdapterTests(unittest.TestCase):
    def _settings(self, *, fail_closed: bool) -> dict:
        return {"fail_closed": fail_closed}

    def test_allow_exits_zero_with_empty_stdout(self) -> None:
        payload = {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
        }
        with patch.object(codex, "read_hook_input", return_value=payload):
            with patch.object(codex, "load_config", return_value={}):
                with patch.object(codex, "resolve_settings", return_value=self._settings(fail_closed=False)):
                    with patch.object(codex, "run_input_check", return_value={}):
                        with patch.object(codex, "emit_secured_notice") as secured:
                            with patch("sys.stdout", new_callable=StringIO) as stdout:
                                with self.assertRaises(SystemExit) as cm:
                                    codex.main()
        self.assertEqual(cm.exception.code, 0)
        self.assertEqual(stdout.getvalue(), "")
        secured.assert_not_called()

    def test_pretool_json_deny_without_dialog(self) -> None:
        payload = {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "Bash",
            "tool_input": {"command": "rm -rf /"},
        }
        with patch.object(codex, "read_hook_input", return_value=payload):
            with patch.object(codex, "load_config", return_value={}):
                with patch.object(codex, "resolve_settings", return_value=self._settings(fail_closed=False)):
                    with patch.object(
                        codex,
                        "run_input_check",
                        side_effect=GuardrailError("blocked by policy", overridable=False),
                    ):
                        with patch.object(codex, "resolve_override") as ask:
                            with patch("sys.stdout", new_callable=StringIO) as stdout:
                                with self.assertRaises(SystemExit) as cm:
                                    codex.main()
        self.assertEqual(cm.exception.code, 0)
        ask.assert_not_called()
        data = json.loads(stdout.getvalue())
        decision = data["hookSpecificOutput"]
        self.assertEqual(decision["hookEventName"], "PreToolUse")
        self.assertEqual(decision["permissionDecision"], "deny")
        self.assertIn("blocked by policy", decision["permissionDecisionReason"])
        self.assertNotIn("ask", stdout.getvalue())

    def test_pretool_dialog_allow(self) -> None:
        payload = {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "Bash",
            "tool_input": {"command": "echo hi"},
        }
        with patch.object(codex, "read_hook_input", return_value=payload):
            with patch.object(codex, "load_config", return_value={}):
                with patch.object(codex, "resolve_settings", return_value=self._settings(fail_closed=False)):
                    with patch.object(
                        codex,
                        "run_input_check",
                        side_effect=GuardrailError("blocked by policy"),
                    ):
                        with patch.object(
                            codex,
                            "resolve_override",
                            return_value=OverrideDecision.ALLOW,
                        ) as ask:
                            with patch("sys.stdout", new_callable=StringIO) as stdout:
                                with self.assertRaises(SystemExit) as cm:
                                    codex.main()
        self.assertEqual(cm.exception.code, 0)
        ask.assert_called_once()
        self.assertEqual(stdout.getvalue(), "")

    def test_pretool_dialog_deny(self) -> None:
        payload = {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "Bash",
            "tool_input": {"command": "echo hi"},
        }
        with patch.object(codex, "read_hook_input", return_value=payload):
            with patch.object(codex, "load_config", return_value={}):
                with patch.object(codex, "resolve_settings", return_value=self._settings(fail_closed=False)):
                    with patch.object(
                        codex,
                        "run_input_check",
                        side_effect=GuardrailError("blocked by policy"),
                    ):
                        with patch.object(
                            codex,
                            "resolve_override",
                            return_value=OverrideDecision.DENY,
                        ):
                            with patch("sys.stdout", new_callable=StringIO) as stdout:
                                with self.assertRaises(SystemExit) as cm:
                                    codex.main()
        self.assertEqual(cm.exception.code, 0)
        data = json.loads(stdout.getvalue())
        self.assertEqual(data["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_prompt_block_without_dialog(self) -> None:
        payload = {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "s1",
            "prompt": "jailbreak",
        }
        with patch.object(codex, "read_hook_input", return_value=payload):
            with patch.object(codex, "load_config", return_value={}):
                with patch.object(codex, "resolve_settings", return_value=self._settings(fail_closed=False)):
                    with patch.object(
                        codex,
                        "run_input_check",
                        side_effect=GuardrailError("blocked by policy", overridable=False),
                    ):
                        with patch.object(codex, "resolve_override") as ask:
                            with patch.object(codex, "emit_secured_notice") as secured:
                                with patch("sys.stdout", new_callable=StringIO) as stdout:
                                    with self.assertRaises(SystemExit) as cm:
                                        codex.main()
        self.assertEqual(cm.exception.code, 0)
        ask.assert_not_called()
        secured.assert_not_called()
        data = json.loads(stdout.getvalue())
        self.assertEqual(data["decision"], "block")
        self.assertIn("blocked by policy", data["reason"])

    def test_prompt_allow_prints_secured_notice(self) -> None:
        payload = {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "s1",
            "prompt": "hello",
        }
        with patch.object(codex, "read_hook_input", return_value=payload):
            with patch.object(codex, "load_config", return_value={}):
                with patch.object(codex, "resolve_settings", return_value=self._settings(fail_closed=False)):
                    with patch.object(codex, "run_input_check", return_value={}):
                        with patch.object(
                            codex,
                            "emit_secured_notice",
                            return_value=SECURED_MESSAGE,
                        ) as secured:
                            with patch("sys.stdout", new_callable=StringIO) as stdout:
                                with self.assertRaises(SystemExit) as cm:
                                    codex.main()
        self.assertEqual(cm.exception.code, 0)
        secured.assert_called_once_with("s1")
        data = json.loads(stdout.getvalue())
        self.assertEqual(data, {"systemMessage": SECURED_MESSAGE})
        self.assertNotIn("additionalContext", stdout.getvalue())

    def test_prompt_allow_second_time_prints_nothing(self) -> None:
        payload = {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "s1",
            "prompt": "hello again",
        }
        with patch.object(codex, "read_hook_input", return_value=payload):
            with patch.object(codex, "load_config", return_value={}):
                with patch.object(codex, "resolve_settings", return_value=self._settings(fail_closed=False)):
                    with patch.object(codex, "run_input_check", return_value={}):
                        with patch.object(codex, "emit_secured_notice", return_value=None):
                            with patch("sys.stdout", new_callable=StringIO) as stdout:
                                with self.assertRaises(SystemExit) as cm:
                                    codex.main()
        self.assertEqual(cm.exception.code, 0)
        self.assertEqual(stdout.getvalue(), "")

    def test_fail_open_prompt_prints_unavailable_notice(self) -> None:
        payload = {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "s1",
            "prompt": "hello",
        }
        with patch.object(codex, "read_hook_input", return_value=payload):
            with patch.object(codex, "load_config", return_value={}):
                with patch.object(codex, "resolve_settings", return_value=self._settings(fail_closed=False)):
                    with patch.object(
                        codex,
                        "run_input_check",
                        side_effect=FireguardUnavailableError("down", reason="unavailable"),
                    ):
                        with patch.object(
                            codex,
                            "handle_service_failure",
                            return_value=UNAVAILABLE_MESSAGE,
                        ):
                            with patch.object(codex, "emit_secured_notice") as secured:
                                with patch("sys.stdout", new_callable=StringIO) as stdout:
                                    with self.assertRaises(SystemExit) as cm:
                                        codex.main()
        self.assertEqual(cm.exception.code, 0)
        secured.assert_not_called()
        data = json.loads(stdout.getvalue())
        self.assertEqual(data, {"systemMessage": UNAVAILABLE_MESSAGE})

    def test_not_configured_prompt_prints_notice(self) -> None:
        payload = {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "s1",
            "prompt": "hello",
        }
        with patch.object(codex, "read_hook_input", return_value=payload):
            with patch.object(codex, "load_config", return_value={}):
                with patch.object(codex, "resolve_settings", side_effect=ValueError("missing")):
                    with patch.object(codex, "fail_closed_from_config", return_value=False):
                        with patch.object(
                            codex,
                            "emit_unavailable_notice",
                            return_value=NOT_CONFIGURED_MESSAGE,
                        ) as unavailable:
                            with patch.object(codex, "emit_secured_notice") as secured:
                                with patch("sys.stdout", new_callable=StringIO) as stdout:
                                    with self.assertRaises(SystemExit) as cm:
                                        codex.main()
        self.assertEqual(cm.exception.code, 0)
        unavailable.assert_called_once_with("s1", reason="not_configured")
        secured.assert_not_called()
        data = json.loads(stdout.getvalue())
        self.assertEqual(data, {"systemMessage": NOT_CONFIGURED_MESSAGE})

    def test_fail_open_exits_zero_with_empty_stdout(self) -> None:
        payload = {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
        }
        with patch.object(codex, "read_hook_input", return_value=payload):
            with patch.object(codex, "load_config", return_value={}):
                with patch.object(codex, "resolve_settings", return_value=self._settings(fail_closed=False)):
                    with patch.object(
                        codex,
                        "run_input_check",
                        side_effect=FireguardUnavailableError("down", reason="unavailable"),
                    ):
                        with patch.object(codex, "handle_service_failure", return_value=None) as failed:
                            with patch("sys.stdout", new_callable=StringIO) as stdout:
                                with self.assertRaises(SystemExit) as cm:
                                    codex.main()
        self.assertEqual(cm.exception.code, 0)
        self.assertEqual(stdout.getvalue(), "")
        failed.assert_called_once()
        self.assertFalse(failed.call_args.kwargs["fail_closed"])

    def test_invalid_stdin_exits_2(self) -> None:
        with patch.object(
            codex,
            "read_hook_input",
            side_effect=json.JSONDecodeError("bad", "", 0),
        ):
            with patch("sys.stderr", new_callable=StringIO):
                with self.assertRaises(SystemExit) as cm:
                    codex.main()
        self.assertEqual(cm.exception.code, 2)

    def test_local_block_skips_dialog(self) -> None:
        payload = {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "Bash",
            "tool_input": {"command": "cat /tmp/.env"},
        }
        with patch.object(codex, "read_hook_input", return_value=payload):
            with patch.object(codex, "load_config", return_value={}):
                with patch.object(codex, "resolve_settings", return_value=self._settings(fail_closed=True)):
                    with patch.object(codex, "resolve_override") as ask:
                        with patch("sys.stdout", new_callable=StringIO) as stdout:
                            with self.assertRaises(SystemExit) as cm:
                                codex.main()
        self.assertEqual(cm.exception.code, 0)
        ask.assert_not_called()
        data = json.loads(stdout.getvalue())
        self.assertEqual(data["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("sensitive", data["hookSpecificOutput"]["permissionDecisionReason"].lower())


if __name__ == "__main__":
    unittest.main()
