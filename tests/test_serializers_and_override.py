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

from core.fireraven_client import evaluate_input_result, pii_violation_message, violation_message
from core.guardrail import GuardrailError
from core.human_override import OverrideDecision, request_human_override, resolve_override
from core.serializers import (
    USER_PROMPT_EVENTS,
    infer_claude_event,
    serialize_claude,
    serialize_cursor,
)


class ViolationMessageTests(unittest.TestCase):
    def test_two_unsafe_policies_message_then_names(self) -> None:
        text = violation_message(
            {
                "policies_guardrail_results": {
                    "policies": [
                        {
                            "name": "no-curl",
                            "is_safe": False,
                            "policy_violation_message": "This message goes against the policies",
                        },
                        {
                            "name": "no-wget",
                            "is_safe": False,
                            "policy_violation_message": "wget blocked",
                        },
                        {"name": "ok", "is_safe": True, "policy_violation_message": "n/a"},
                    ]
                }
            }
        )
        self.assertEqual(
            text,
            "This message goes against the policies\n"
            "wget blocked\n\n"
            "The following policies were triggered:\n"
            "- no-curl\n"
            "- no-wget",
        )
        self.assertNotIn("ok", text)

    def test_security_and_policy_both_appear(self) -> None:
        text = violation_message(
            {
                "security_guardrail_results": {
                    "is_safe": False,
                    "security_violation_message": "prompt injection",
                },
                "policies_guardrail_results": {
                    "policies": [
                        {
                            "name": "no-curl",
                            "is_safe": False,
                            "policy_violation_message": "blocked",
                        }
                    ]
                },
            }
        )
        self.assertEqual(
            text,
            "blocked\n\n"
            "The following policies were triggered:\n"
            "- Security: prompt injection\n"
            "- no-curl",
        )

    def test_single_policy_message_then_name(self) -> None:
        text = violation_message(
            {
                "policies_guardrail_results": {
                    "policies": [
                        {
                            "name": "CURL request",
                            "is_safe": False,
                            "policy_violation_message": "This message goes against the policies",
                        }
                    ]
                }
            }
        )
        self.assertEqual(
            text,
            "This message goes against the policies\n\n"
            "The following policies were triggered:\n"
            "- CURL request",
        )

    def test_duplicate_messages_deduped(self) -> None:
        text = violation_message(
            {
                "policies_guardrail_results": {
                    "policies": [
                        {
                            "name": "no-curl",
                            "is_safe": False,
                            "policy_violation_message": "This message goes against the policies",
                        },
                        {
                            "name": "no-wget",
                            "is_safe": False,
                            "policy_violation_message": "This message goes against the policies",
                        },
                    ]
                }
            }
        )
        self.assertEqual(
            text,
            "This message goes against the policies\n\n"
            "The following policies were triggered:\n"
            "- no-curl\n"
            "- no-wget",
        )

    def test_security_only(self) -> None:
        text = violation_message(
            {
                "security_guardrail_results": {
                    "is_safe": False,
                    "security_violation_message": "prompt injection",
                },
                "policies_guardrail_results": {"policies": []},
            }
        )
        self.assertEqual(
            text,
            "The following policies were triggered:\n"
            "- Security: prompt injection",
        )

    def test_all_safe_returns_default(self) -> None:
        text = violation_message(
            {
                "security_guardrail_results": {"is_safe": True},
                "policies_guardrail_results": {
                    "policies": [{"name": "ok", "is_safe": True}]
                },
            }
        )
        self.assertEqual(text, "Blocked by Fireraven FireGuard.")


_PII_ONLY_UNSAFE = {
    "is_safe": False,
    "security_guardrail_results": {"is_safe": True},
    "policies_guardrail_results": {"is_safe": True, "policies": []},
    "pii_guardrail_results": {
        "is_safe": False,
        "masked_text": "Hi my name is [PERSON_NAME]",
    },
    "overall_response": "Hi my name is [PERSON_NAME]",
}

_POLICY_AND_PII_UNSAFE = {
    "is_safe": False,
    "security_guardrail_results": {"is_safe": True},
    "policies_guardrail_results": {
        "is_safe": False,
        "policies": [
            {
                "name": "no-jailbreak",
                "is_safe": False,
                "policy_violation_message": "blocked by policy",
            }
        ],
    },
    "pii_guardrail_results": {
        "is_safe": False,
        "masked_text": "Hi [PERSON_NAME]",
    },
}


class EvaluateInputResultTests(unittest.TestCase):
    def test_pii_only_allows_when_not_enforced(self) -> None:
        evaluate_input_result(_PII_ONLY_UNSAFE, enforce_pii=False)

    def test_pii_only_blocks_when_enforced(self) -> None:
        with self.assertRaises(GuardrailError) as cm:
            evaluate_input_result(_PII_ONLY_UNSAFE, enforce_pii=True)
        self.assertFalse(cm.exception.overridable)
        self.assertIn("PII detected", str(cm.exception))
        self.assertIn("[PERSON_NAME]", str(cm.exception))

    def test_policy_wins_over_pii_when_both_unsafe(self) -> None:
        with self.assertRaises(GuardrailError) as cm:
            evaluate_input_result(_POLICY_AND_PII_UNSAFE, enforce_pii=True)
        self.assertFalse(cm.exception.overridable)
        message = str(cm.exception)
        self.assertIn("blocked by policy", message)
        self.assertIn("PII detected", message)
        self.assertIn("Hi [PERSON_NAME]", message)
        self.assertLess(message.index("blocked by policy"), message.index("PII detected"))

    def test_security_blocks_even_without_pii_enforce(self) -> None:
        result = {
            "is_safe": False,
            "security_guardrail_results": {
                "is_safe": False,
                "security_violation_message": "prompt injection",
            },
            "pii_guardrail_results": {"is_safe": False, "masked_text": "x"},
        }
        with self.assertRaises(GuardrailError) as cm:
            evaluate_input_result(result, enforce_pii=False)
        self.assertIn("Security", str(cm.exception))

    def test_pii_message_without_masked_text(self) -> None:
        text = pii_violation_message(
            {"pii_guardrail_results": {"is_safe": False, "masked_text": None}}
        )
        self.assertIn("PII detected", text)
        self.assertNotIn("Suggested redacted", text)

    def test_user_prompt_events_set(self) -> None:
        self.assertIn("beforeSubmitPrompt", USER_PROMPT_EVENTS)
        self.assertIn("pre_user_prompt", USER_PROMPT_EVENTS)
        self.assertIn("UserPromptSubmit", USER_PROMPT_EVENTS)
        self.assertIn("userPromptSubmitted", USER_PROMPT_EVENTS)
        self.assertNotIn("beforeMCPExecution", USER_PROMPT_EVENTS)
        self.assertNotIn("PreToolUse", USER_PROMPT_EVENTS)


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
        self.assertEqual(
            infer_claude_event({"hook_event_name": "preToolUse", "tool_name": "Read"}),
            "PreToolUse",
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


class HookIoTests(unittest.TestCase):
    def test_read_hook_input_strips_utf8_bom(self) -> None:
        from core.hook_io import read_hook_input

        payload = {"hook_event_name": "preToolUse", "tool_name": "Read"}
        raw = b"\xef\xbb\xbf" + json.dumps(payload).encode("utf-8")
        buffer = mock.Mock()
        buffer.read.return_value = raw
        stdin = mock.Mock()
        stdin.buffer = buffer
        with mock.patch("core.hook_io.sys.stdin", stdin):
            parsed = read_hook_input()
        self.assertEqual(parsed["tool_name"], "Read")

    def test_read_hook_input_plain_utf8(self) -> None:
        from core.hook_io import read_hook_input

        payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash"}
        buffer = mock.Mock()
        buffer.read.return_value = json.dumps(payload).encode("utf-8")
        stdin = mock.Mock()
        stdin.buffer = buffer
        with mock.patch("core.hook_io.sys.stdin", stdin):
            parsed = read_hook_input()
        self.assertEqual(parsed["tool_name"], "Bash")


class HumanOverrideTests(unittest.TestCase):
    def test_linux_unavailable_without_display(self) -> None:
        with mock.patch.dict("os.environ", {"DISPLAY": "", "WAYLAND_DISPLAY": ""}, clear=False):
            # Clear display vars explicitly.
            env = {k: v for k, v in __import__("os").environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY")}
            with mock.patch.dict("os.environ", env, clear=True):
                with mock.patch("core.human_override.platform.system", return_value="Linux"):
                    with mock.patch("builtins.print") as printer:
                        decision = request_human_override("t", "m")
        self.assertEqual(decision, OverrideDecision.UNAVAILABLE)
        hint = " ".join(str(c) for c in printer.call_args_list)
        self.assertIn("yad", hint)

    def test_yad_preferred_over_zenity(self) -> None:
        with mock.patch.dict("os.environ", {"DISPLAY": ":0"}, clear=False):
            with mock.patch("core.human_override.platform.system", return_value="Linux"):
                with mock.patch(
                    "core.human_override.shutil.which",
                    side_effect=lambda c: c in ("yad", "zenity"),
                ):
                    with mock.patch(
                        "core.human_override.subprocess.run",
                        return_value=mock.Mock(returncode=0),
                    ) as run:
                        decision = request_human_override("t", "blocked")
        self.assertEqual(decision, OverrideDecision.ALLOW)
        argv = run.call_args.args[0]
        self.assertEqual(argv[0], "yad")
        self.assertNotIn("--question", argv)
        self.assertIn("--text-align=left", argv)
        self.assertIn("--window-icon=", argv)

    def test_yad_allow(self) -> None:
        with mock.patch.dict("os.environ", {"DISPLAY": ":0"}, clear=False):
            with mock.patch("core.human_override.platform.system", return_value="Linux"):
                with mock.patch(
                    "core.human_override.shutil.which",
                    side_effect=lambda c: c == "yad",
                ):
                    with mock.patch(
                        "core.human_override.subprocess.run",
                        return_value=mock.Mock(returncode=0),
                    ):
                        decision = request_human_override("t", "blocked")
        self.assertEqual(decision, OverrideDecision.ALLOW)

    def test_yad_deny(self) -> None:
        with mock.patch.dict("os.environ", {"DISPLAY": ":0"}, clear=False):
            with mock.patch("core.human_override.platform.system", return_value="Linux"):
                with mock.patch(
                    "core.human_override.shutil.which",
                    side_effect=lambda c: c == "yad",
                ):
                    with mock.patch(
                        "core.human_override.subprocess.run",
                        return_value=mock.Mock(returncode=1),
                    ):
                        decision = request_human_override("t", "blocked")
        self.assertEqual(decision, OverrideDecision.DENY)

    def test_yad_timeout_is_deny(self) -> None:
        with mock.patch.dict("os.environ", {"DISPLAY": ":0"}, clear=False):
            with mock.patch("core.human_override.platform.system", return_value="Linux"):
                with mock.patch(
                    "core.human_override.shutil.which",
                    side_effect=lambda c: c == "yad",
                ):
                    with mock.patch(
                        "core.human_override.subprocess.run",
                        return_value=mock.Mock(returncode=70),
                    ):
                        decision = request_human_override("t", "blocked")
        self.assertEqual(decision, OverrideDecision.DENY)

    def test_zenity_when_yad_absent(self) -> None:
        with mock.patch.dict("os.environ", {"DISPLAY": ":0"}, clear=False):
            with mock.patch("core.human_override.platform.system", return_value="Linux"):
                with mock.patch(
                    "core.human_override.shutil.which",
                    side_effect=lambda c: c == "zenity",
                ):
                    with mock.patch(
                        "core.human_override.subprocess.run",
                        return_value=mock.Mock(returncode=0),
                    ) as run:
                        decision = request_human_override("t", "blocked")
        self.assertEqual(decision, OverrideDecision.ALLOW)
        self.assertEqual(run.call_args.args[0][0], "zenity")

    def test_zenity_timeout_and_unknown_are_deny(self) -> None:
        with mock.patch.dict("os.environ", {"DISPLAY": ":0"}, clear=False):
            with mock.patch("core.human_override.platform.system", return_value="Linux"):
                with mock.patch(
                    "core.human_override.shutil.which",
                    side_effect=lambda c: c == "zenity",
                ):
                    for code in (1, 5, 99):
                        with mock.patch(
                            "core.human_override.subprocess.run",
                            return_value=mock.Mock(returncode=code),
                        ):
                            decision = request_human_override("t", "blocked")
                        self.assertEqual(decision, OverrideDecision.DENY, msg=f"code={code}")

    def test_unavailable_hint_when_no_dialog_tool(self) -> None:
        with mock.patch.dict("os.environ", {"DISPLAY": ":0"}, clear=False):
            with mock.patch("core.human_override.platform.system", return_value="Linux"):
                with mock.patch("core.human_override.shutil.which", return_value=None):
                    with mock.patch("builtins.print") as printer:
                        decision = request_human_override("t", "m")
        self.assertEqual(decision, OverrideDecision.UNAVAILABLE)
        hint = " ".join(str(c) for c in printer.call_args_list)
        self.assertIn("install yad", hint)


class ResolveOverrideTests(unittest.TestCase):
    def test_non_overridable_skips_dialog(self) -> None:
        with mock.patch("core.human_override.request_human_override") as ask:
            decision = resolve_override(
                title="t",
                message="m",
                session_id="s",
                event="pre_run_command",
                overridable=False,
                event_allows_override=True,
            )
        self.assertEqual(decision, OverrideDecision.DENY)
        ask.assert_not_called()

    def test_ineligible_event_skips_dialog(self) -> None:
        with mock.patch("core.human_override.request_human_override") as ask:
            decision = resolve_override(
                title="t",
                message="m",
                session_id="s",
                event="pre_user_prompt",
                overridable=True,
                event_allows_override=False,
            )
        self.assertEqual(decision, OverrideDecision.DENY)
        ask.assert_not_called()


class WindsurfAdapterOverrideTests(unittest.TestCase):
    def test_policy_block_prompts_dialog_then_allows(self) -> None:
        from adapters import windsurf as windsurf_adapter
        from core.guardrail import GuardrailError

        payload = {
            "agent_action_name": "pre_run_command",
            "trajectory_id": "s1",
            "tool_info": {"command_line": "rm -rf /"},
        }
        with mock.patch.object(windsurf_adapter, "read_hook_input", return_value=payload):
            with mock.patch.object(windsurf_adapter, "load_config", return_value={}):
                with mock.patch.object(
                    windsurf_adapter,
                    "resolve_settings",
                    return_value={"fail_closed": False},
                ):
                    with mock.patch.object(
                        windsurf_adapter,
                        "run_input_check",
                        side_effect=GuardrailError("blocked by policy"),
                    ):
                        with mock.patch.object(
                            windsurf_adapter,
                            "resolve_override",
                            return_value=OverrideDecision.ALLOW,
                        ) as ask:
                            with self.assertRaises(SystemExit) as cm:
                                windsurf_adapter.main()
        self.assertEqual(cm.exception.code, 0)
        ask.assert_called_once()

    def test_prompt_policy_hard_denies_without_dialog(self) -> None:
        from adapters import windsurf as windsurf_adapter
        from core.guardrail import GuardrailError

        payload = {
            "agent_action_name": "pre_user_prompt",
            "trajectory_id": "s1",
            "tool_info": {"user_prompt": "jailbreak"},
        }
        with mock.patch.object(windsurf_adapter, "read_hook_input", return_value=payload):
            with mock.patch.object(windsurf_adapter, "load_config", return_value={}):
                with mock.patch.object(
                    windsurf_adapter,
                    "resolve_settings",
                    return_value={"fail_closed": False},
                ):
                    with mock.patch.object(
                        windsurf_adapter,
                        "run_input_check",
                        side_effect=GuardrailError("blocked by policy"),
                    ):
                        with mock.patch(
                            "core.human_override.request_human_override",
                        ) as ask:
                            with self.assertRaises(SystemExit) as cm:
                                windsurf_adapter.main()
        self.assertEqual(cm.exception.code, 2)
        ask.assert_not_called()


class CursorPretoolDeferTests(unittest.TestCase):
    def test_defer_shell_read_mcp(self) -> None:
        from adapters.cursor import pretool_deferred_to_specialized

        self.assertTrue(pretool_deferred_to_specialized("Shell"))
        self.assertTrue(pretool_deferred_to_specialized("Read"))
        self.assertTrue(pretool_deferred_to_specialized("MCP:server-tool"))
        self.assertTrue(pretool_deferred_to_specialized("mcp__server__tool"))
        self.assertFalse(pretool_deferred_to_specialized("Write"))
        self.assertFalse(pretool_deferred_to_specialized("Grep"))
        self.assertFalse(pretool_deferred_to_specialized("Delete"))
        self.assertFalse(pretool_deferred_to_specialized("Task"))

    def test_pretool_shell_allows_without_fireguard(self) -> None:
        from adapters import cursor as cursor_adapter

        payload = {
            "hook_event_name": "preToolUse",
            "conversation_id": "s1",
            "tool_name": "Shell",
            "tool_input": {"command": "ls"},
        }
        with mock.patch.object(cursor_adapter, "read_hook_input", return_value=payload):
            with mock.patch.object(cursor_adapter, "run_input_check") as check:
                with mock.patch("builtins.print") as printer:
                    with self.assertRaises(SystemExit) as cm:
                        cursor_adapter.main()
        self.assertEqual(cm.exception.code, 0)
        check.assert_not_called()
        printer.assert_called()
        self.assertIn("allow", printer.call_args.args[0])

    def test_before_submit_prompt_enforces_pii(self) -> None:
        from adapters import cursor as cursor_adapter

        payload = {
            "hook_event_name": "beforeSubmitPrompt",
            "conversation_id": "s1",
            "prompt": "hello",
        }
        with mock.patch.object(cursor_adapter, "read_hook_input", return_value=payload):
            with mock.patch.object(cursor_adapter, "load_config", return_value={}):
                with mock.patch.object(
                    cursor_adapter,
                    "resolve_settings",
                    return_value={"fail_closed": False},
                ):
                    with mock.patch.object(
                        cursor_adapter, "run_input_check", return_value={}
                    ) as check:
                        with mock.patch.object(
                            cursor_adapter, "emit_secured_notice", return_value=None
                        ):
                            with mock.patch("builtins.print"):
                                with self.assertRaises(SystemExit):
                                    cursor_adapter.main()
        check.assert_called_once()
        self.assertTrue(check.call_args.kwargs.get("enforce_pii"))

    def test_before_mcp_does_not_enforce_pii(self) -> None:
        from adapters import cursor as cursor_adapter

        payload = {
            "hook_event_name": "beforeMCPExecution",
            "conversation_id": "s1",
            "tool_name": "search",
            "tool_input": {"query": "John Doe"},
        }
        with mock.patch.object(cursor_adapter, "read_hook_input", return_value=payload):
            with mock.patch.object(cursor_adapter, "load_config", return_value={}):
                with mock.patch.object(
                    cursor_adapter,
                    "resolve_settings",
                    return_value={"fail_closed": False},
                ):
                    with mock.patch.object(
                        cursor_adapter, "run_input_check", return_value={}
                    ) as check:
                        with mock.patch("builtins.print"):
                            with self.assertRaises(SystemExit):
                                cursor_adapter.main()
        check.assert_called_once()
        self.assertFalse(check.call_args.kwargs.get("enforce_pii"))


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
                            "resolve_override",
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
                    with mock.patch(
                        "core.human_override.request_human_override",
                    ) as ask:
                        with self.assertRaises(SystemExit) as cm:
                            cursor_adapter.main()
        self.assertEqual(cm.exception.code, 0)
        ask.assert_not_called()


class ClaudeAdapterOverrideTests(unittest.TestCase):
    def test_vscode_pretool_policy_deny_returns_deny_json(self) -> None:
        from adapters import claude as claude_adapter
        from core.guardrail import GuardrailError
        from core.human_override import OverrideDecision

        payload = {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "Bash",
            "tool_input": {"command": "evil"},
        }
        with mock.patch.dict(
            "os.environ",
            {"CLAUDE_CODE_ENTRYPOINT": "claude-vscode"},
            clear=False,
        ):
            with mock.patch.object(claude_adapter, "read_hook_input", return_value=payload):
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
                            with mock.patch.object(
                                claude_adapter,
                                "resolve_override",
                                return_value=OverrideDecision.DENY,
                            ) as override:
                                with mock.patch("builtins.print") as printer:
                                    with self.assertRaises(SystemExit) as cm:
                                        claude_adapter.main()
        self.assertEqual(cm.exception.code, 0)
        override.assert_called_once()
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
            "deny",
        )
        self.assertEqual(
            printed["hookSpecificOutput"]["permissionDecisionReason"],
            "blocked by policy",
        )

    def test_vscode_pretool_policy_allow_exits_0_without_deny_json(self) -> None:
        from adapters import claude as claude_adapter
        from core.guardrail import GuardrailError
        from core.human_override import OverrideDecision

        payload = {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "Bash",
            "tool_input": {"command": "evil"},
        }
        with mock.patch.dict(
            "os.environ",
            {"CLAUDE_CODE_ENTRYPOINT": "claude-vscode"},
            clear=False,
        ):
            with mock.patch.object(claude_adapter, "read_hook_input", return_value=payload):
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
                            with mock.patch.object(
                                claude_adapter,
                                "resolve_override",
                                return_value=OverrideDecision.ALLOW,
                            ) as override:
                                with mock.patch("builtins.print") as printer:
                                    with self.assertRaises(SystemExit) as cm:
                                        claude_adapter.main()
        self.assertEqual(cm.exception.code, 0)
        override.assert_called_once()
        for call in printer.call_args_list:
            args = call.args
            if args and isinstance(args[0], str) and args[0].startswith("{"):
                printed = json.loads(args[0])
                self.assertNotEqual(
                    printed.get("hookSpecificOutput", {}).get("permissionDecision"),
                    "deny",
                )

    def test_desktop_pretool_uses_os_dialog(self) -> None:
        from adapters import claude as claude_adapter
        from core.guardrail import GuardrailError
        from core.human_override import OverrideDecision

        payload = {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "Bash",
            "tool_input": {"command": "evil"},
        }
        with mock.patch.dict(
            "os.environ",
            {"CLAUDE_CODE_ENTRYPOINT": "claude-desktop"},
            clear=False,
        ):
            with mock.patch.object(claude_adapter, "read_hook_input", return_value=payload):
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
                            with mock.patch.object(
                                claude_adapter,
                                "resolve_override",
                                return_value=OverrideDecision.DENY,
                            ) as override:
                                with mock.patch("builtins.print"):
                                    with self.assertRaises(SystemExit) as cm:
                                        claude_adapter.main()
        self.assertEqual(cm.exception.code, 0)
        override.assert_called_once()

    def test_cli_pretool_policy_returns_ask_json(self) -> None:
        from adapters import claude as claude_adapter
        from core.guardrail import GuardrailError

        payload = {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "Bash",
            "tool_input": {"command": "evil"},
        }
        env = {k: v for k, v in __import__("os").environ.items() if k != "CLAUDE_CODE_ENTRYPOINT"}
        env["CLAUDE_CODE_ENTRYPOINT"] = "cli"
        with mock.patch.dict("os.environ", env, clear=True):
            with mock.patch.object(claude_adapter, "read_hook_input", return_value=payload):
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
                            with mock.patch.object(
                                claude_adapter,
                                "resolve_override",
                            ) as override:
                                with mock.patch("builtins.print") as printer:
                                    with self.assertRaises(SystemExit) as cm:
                                        claude_adapter.main()
        self.assertEqual(cm.exception.code, 0)
        override.assert_not_called()
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
        self.assertEqual(
            printed["hookSpecificOutput"]["permissionDecisionReason"],
            "blocked by policy",
        )

    def test_cursor_bridged_invocation_is_skipped(self) -> None:
        from adapters import claude as claude_adapter

        payload = {
            "hook_event_name": "preToolUse",
            "cursor_version": "3.13.10",
            "session_id": "s1",
            "tool_name": "Read",
            "tool_input": {"file_path": "/tmp/a"},
        }
        with mock.patch.object(claude_adapter, "read_hook_input", return_value=payload):
            with mock.patch.object(claude_adapter, "run_input_check") as check:
                with self.assertRaises(SystemExit) as cm:
                    claude_adapter.main()
        self.assertEqual(cm.exception.code, 0)
        check.assert_not_called()

    def test_non_overridable_pretool_exits_2(self) -> None:
        from adapters import claude as claude_adapter
        from core.guardrail import GuardrailError

        payload = {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "Read",
            "tool_input": {"file_path": "/proj/.env"},
        }
        with mock.patch.object(claude_adapter, "read_hook_input", return_value=payload):
            with mock.patch.object(claude_adapter, "load_config", return_value={}):
                with mock.patch.object(
                    claude_adapter,
                    "resolve_settings",
                    return_value={"fail_closed": False},
                ):
                    with mock.patch.object(
                        claude_adapter,
                        "run_input_check",
                        side_effect=GuardrailError(
                            "Access to sensitive path blocked locally",
                            overridable=False,
                        ),
                    ):
                        with mock.patch.object(
                            claude_adapter,
                            "resolve_override",
                        ) as override:
                            with self.assertRaises(SystemExit) as cm:
                                claude_adapter.main()
        self.assertEqual(cm.exception.code, 2)
        override.assert_not_called()

    def test_user_prompt_still_exits_2(self) -> None:
        from adapters import claude as claude_adapter
        from core.guardrail import GuardrailError

        payload = {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "s1",
            "prompt": "jailbreak",
        }
        with mock.patch.object(claude_adapter, "read_hook_input", return_value=payload):
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
