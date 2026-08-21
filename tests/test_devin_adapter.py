"""Tests for Devin Local adapter."""

from __future__ import annotations

import json
import unittest
from io import StringIO
from unittest.mock import patch

from adapters import devin
from core.guardrail import GuardrailError
from core.human_override import OverrideDecision
from core.serializers import infer_devin_event, serialize_devin


class SerializeDevinTests(unittest.TestCase):
    def test_pre_tool_use(self) -> None:
        text = serialize_devin(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "exec",
                "tool_input": {"command": "ls"},
            }
        )
        self.assertIn("Devin tool: exec", text or "")
        self.assertIn("ls", text or "")

    def test_local_block_on_sensitive_path(self) -> None:
        text = serialize_devin(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "read",
                "tool_input": {"path": "/tmp/.env"},
            }
        )
        self.assertTrue(text and text.startswith("__LOCAL_BLOCK__:"))

    def test_user_prompt(self) -> None:
        text = serialize_devin({"hook_event_name": "UserPromptSubmit", "prompt": "hello"})
        self.assertEqual(text, "hello")

    def test_infer_events(self) -> None:
        self.assertEqual(
            infer_devin_event({"hook_event_name": "PreToolUse", "tool_name": "exec"}),
            "PreToolUse",
        )


class DevinAdapterTests(unittest.TestCase):
    def test_pretool_dialog_allow(self) -> None:
        payload = {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "exec",
            "tool_input": {"command": "evil"},
        }
        with patch.object(devin, "read_hook_input", return_value=payload):
            with patch.object(devin, "load_config", return_value={}):
                with patch.object(
                    devin,
                    "resolve_settings",
                    return_value={"fail_closed": False},
                ):
                    with patch.object(
                        devin,
                        "run_input_check",
                        side_effect=GuardrailError("blocked by policy"),
                    ):
                        with patch.object(
                            devin,
                            "resolve_override",
                            return_value=OverrideDecision.ALLOW,
                        ) as ask:
                            with patch("sys.stdout", new_callable=StringIO) as stdout:
                                with self.assertRaises(SystemExit) as cm:
                                    devin.main()
        self.assertEqual(cm.exception.code, 0)
        ask.assert_called_once()
        data = json.loads(stdout.getvalue())
        self.assertEqual(data["decision"], "approve")

    def test_pretool_dialog_deny_blocks(self) -> None:
        payload = {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "exec",
            "tool_input": {"command": "evil"},
        }
        with patch.object(devin, "read_hook_input", return_value=payload):
            with patch.object(devin, "load_config", return_value={}):
                with patch.object(
                    devin,
                    "resolve_settings",
                    return_value={"fail_closed": False},
                ):
                    with patch.object(
                        devin,
                        "run_input_check",
                        side_effect=GuardrailError("blocked by policy"),
                    ):
                        with patch.object(
                            devin,
                            "resolve_override",
                            return_value=OverrideDecision.DENY,
                        ):
                            with patch("sys.stdout", new_callable=StringIO) as stdout:
                                with self.assertRaises(SystemExit) as cm:
                                    devin.main()
        self.assertEqual(cm.exception.code, 0)
        data = json.loads(stdout.getvalue())
        self.assertEqual(data["decision"], "block")
        self.assertIn("blocked by policy", data["reason"])

    def test_prompt_hard_denies_without_dialog(self) -> None:
        payload = {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "s1",
            "prompt": "jailbreak",
        }
        with patch.object(devin, "read_hook_input", return_value=payload):
            with patch.object(devin, "load_config", return_value={}):
                with patch.object(
                    devin,
                    "resolve_settings",
                    return_value={"fail_closed": False},
                ):
                    with patch.object(
                        devin,
                        "run_input_check",
                        side_effect=GuardrailError("blocked by policy"),
                    ):
                        with patch(
                            "core.human_override.request_human_override",
                        ) as ask:
                            with self.assertRaises(SystemExit) as cm:
                                devin.main()
        self.assertEqual(cm.exception.code, 2)
        ask.assert_not_called()

    def test_local_block_skips_dialog(self) -> None:
        payload = {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "read",
            "tool_input": {"path": "/tmp/.env"},
        }
        with patch.object(devin, "read_hook_input", return_value=payload):
            with patch.object(devin, "load_config", return_value={}):
                with patch.object(
                    devin,
                    "resolve_settings",
                    return_value={"fail_closed": True},
                ):
                    with patch(
                        "core.human_override.request_human_override",
                    ) as ask:
                        with patch("sys.stdout", new_callable=StringIO) as stdout:
                            with self.assertRaises(SystemExit) as cm:
                                devin.main()
        self.assertEqual(cm.exception.code, 0)
        ask.assert_not_called()
        data = json.loads(stdout.getvalue())
        self.assertEqual(data["decision"], "block")
        self.assertIn("sensitive", data["reason"].lower())


if __name__ == "__main__":
    unittest.main()
