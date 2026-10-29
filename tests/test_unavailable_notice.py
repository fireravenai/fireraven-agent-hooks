from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.fireraven_client import classify_api_error
from core.guardrail import FireguardUnavailableError, GuardrailError, resolve_service_failure
from core.unavailable_notice import (
    NO_CREDITS_MESSAGE,
    NOT_CONFIGURED_MESSAGE,
    UNAVAILABLE_MESSAGE,
    consume_unavailable_notice,
    emit_unavailable_notice,
    notice_message,
)


class UnavailableNoticeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self._hooks_root = Path(self._tmpdir.name)
        self._patcher = mock.patch("core.session_store.hooks_root", return_value=self._hooks_root)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def test_notice_message_variants(self) -> None:
        self.assertEqual(notice_message("unavailable"), UNAVAILABLE_MESSAGE)
        self.assertEqual(notice_message("not_configured"), NOT_CONFIGURED_MESSAGE)
        self.assertEqual(notice_message("no_credits"), NO_CREDITS_MESSAGE)
        self.assertEqual(notice_message("unknown"), UNAVAILABLE_MESSAGE)

    def test_consume_once_then_none(self) -> None:
        first = consume_unavailable_notice("sess-1")
        second = consume_unavailable_notice("sess-1")
        self.assertEqual(first, UNAVAILABLE_MESSAGE)
        self.assertIsNone(second)

    def test_consume_uses_first_reason_only(self) -> None:
        first = consume_unavailable_notice("sess-reason", reason="no_credits")
        second = consume_unavailable_notice("sess-reason", reason="not_configured")
        self.assertEqual(first, NO_CREDITS_MESSAGE)
        self.assertIsNone(second)

    def test_emit_logs_and_toasts_once(self) -> None:
        with mock.patch("core.unavailable_notice.show_unavailable_toast") as toast:
            with mock.patch("builtins.print") as printer:
                first = emit_unavailable_notice("sess-2")
                second = emit_unavailable_notice("sess-2")
        self.assertEqual(first, UNAVAILABLE_MESSAGE)
        self.assertIsNone(second)
        toast.assert_called_once_with(UNAVAILABLE_MESSAGE)
        printer.assert_called_once()
        payload = json.loads(printer.call_args.args[0])
        self.assertEqual(payload["event"], "fireguard_unavailable")
        self.assertEqual(payload["message"], UNAVAILABLE_MESSAGE)


class ClassifyApiErrorTests(unittest.TestCase):
    def test_http_402_is_no_credits(self) -> None:
        self.assertEqual(classify_api_error(RuntimeError("HTTP 402: payment required")), "no_credits")

    def test_http_412_is_no_credits(self) -> None:
        self.assertEqual(
            classify_api_error(RuntimeError("HTTP 412: not enough credits")),
            "no_credits",
        )

    def test_other_http_is_unavailable(self) -> None:
        self.assertEqual(classify_api_error(RuntimeError("HTTP 503: unavailable")), "unavailable")


class ResolveServiceFailureTests(unittest.TestCase):
    def test_unavailable_error_uses_reason(self) -> None:
        exc = FireguardUnavailableError(reason="not_configured")
        self.assertEqual(resolve_service_failure(exc), "not_configured")

    def test_runtime_error_uses_classifier(self) -> None:
        exc = RuntimeError("HTTP 402: no credits")
        self.assertEqual(resolve_service_failure(exc), "no_credits")


class CursorFailOpenNoticeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self._hooks_root = Path(self._tmpdir.name)
        self._patcher = mock.patch("core.session_store.hooks_root", return_value=self._hooks_root)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def _run_cursor(self, *, side_effect: Exception) -> str:
        from adapters import cursor as cursor_adapter

        payload = {
            "hook_event_name": "beforeSubmitPrompt",
            "conversation_id": "cursor-sess",
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
                        cursor_adapter,
                        "run_input_check",
                        side_effect=side_effect,
                    ):
                        with mock.patch("core.unavailable_notice.show_unavailable_toast"):
                            with mock.patch("builtins.print") as printer:
                                with self.assertRaises(SystemExit) as cm:
                                    cursor_adapter.main()
        self.assertEqual(cm.exception.code, 0)
        stdout_calls = [
            c.args[0]
            for c in printer.call_args_list
            if c.args and isinstance(c.args[0], str) and "continue" in c.args[0]
        ]
        self.assertTrue(stdout_calls)
        return stdout_calls[-1]

    def test_fail_open_includes_user_message_once(self) -> None:
        first_payload = json.loads(self._run_cursor(side_effect=RuntimeError("HTTP 503")))
        self.assertTrue(first_payload.get("continue"))
        self.assertEqual(first_payload.get("user_message"), UNAVAILABLE_MESSAGE)

        second_payload = json.loads(self._run_cursor(side_effect=RuntimeError("HTTP 503")))
        self.assertTrue(second_payload.get("continue"))
        self.assertNotIn("user_message", second_payload)

    def test_missing_config_fail_open(self) -> None:
        payload = json.loads(
            self._run_cursor(
                side_effect=FireguardUnavailableError(
                    "FIRERAVEN_GUARDRAILS_API_KEY is not configured.",
                    reason="not_configured",
                ),
            )
        )
        self.assertTrue(payload.get("continue"))
        self.assertEqual(payload.get("user_message"), NOT_CONFIGURED_MESSAGE)

    def test_no_credits_fail_open(self) -> None:
        payload = json.loads(self._run_cursor(side_effect=RuntimeError("HTTP 402: no credits")))
        self.assertTrue(payload.get("continue"))
        self.assertEqual(payload.get("user_message"), NO_CREDITS_MESSAGE)

    def test_missing_config_fail_closed_denies(self) -> None:
        from adapters import cursor as cursor_adapter

        payload = {
            "hook_event_name": "beforeSubmitPrompt",
            "conversation_id": "cursor-sess",
            "prompt": "hello",
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
                        "run_input_check",
                        side_effect=FireguardUnavailableError(
                            "FIRERAVEN_GUARDRAILS_API_KEY is not configured.",
                            reason="not_configured",
                        ),
                    ):
                        with mock.patch("builtins.print") as printer:
                            with self.assertRaises(SystemExit) as cm:
                                cursor_adapter.main()
        self.assertEqual(cm.exception.code, 0)
        out = json.loads(printer.call_args.args[0])
        self.assertFalse(out.get("continue"))
        self.assertIn("not configured", out.get("user_message", "").lower())

    def test_policy_violation_still_denies(self) -> None:
        from adapters import cursor as cursor_adapter

        payload = {
            "hook_event_name": "beforeSubmitPrompt",
            "conversation_id": "cursor-sess",
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
                        cursor_adapter,
                        "run_input_check",
                        side_effect=GuardrailError("blocked by policy"),
                    ):
                        with mock.patch("builtins.print") as printer:
                            with self.assertRaises(SystemExit) as cm:
                                cursor_adapter.main()
        self.assertEqual(cm.exception.code, 0)
        out = json.loads(printer.call_args.args[0])
        self.assertFalse(out.get("continue"))


class ClaudeFailOpenNoticeTests(unittest.TestCase):
    def test_missing_config_fail_open_exits_zero(self) -> None:
        from adapters import claude as claude_adapter

        payload = {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "claude-sess",
            "prompt": "hello",
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
                        side_effect=FireguardUnavailableError(
                            reason="not_configured",
                        ),
                    ):
                        with mock.patch("core.unavailable_notice.show_unavailable_toast"):
                            with self.assertRaises(SystemExit) as cm:
                                claude_adapter.main()
        self.assertEqual(cm.exception.code, 0)


class ToastIconTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self._hooks_root = Path(self._tmpdir.name)
        self._patcher = mock.patch("core.unavailable_notice.hooks_root", return_value=self._hooks_root)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def _place_icon(self) -> Path:
        assets = self._hooks_root / "assets"
        assets.mkdir(parents=True, exist_ok=True)
        icon = assets / "fireraven.ico"
        icon.write_bytes(b"fake-ico")
        return icon

    def test_toast_icon_path_missing(self) -> None:
        from core.unavailable_notice import toast_icon_path

        self.assertIsNone(toast_icon_path())

    def test_toast_icon_path_present(self) -> None:
        from core.unavailable_notice import toast_icon_path

        icon = self._place_icon()
        self.assertEqual(toast_icon_path(), icon)

    def test_linux_toast_includes_icon(self) -> None:
        from core.unavailable_notice import _linux_toast

        icon = self._place_icon()
        with mock.patch("core.unavailable_notice.shutil.which", return_value="/usr/bin/notify-send"):
            with mock.patch("core.unavailable_notice.subprocess.Popen") as popen:
                _linux_toast("hello")
        cmd = popen.call_args.args[0]
        self.assertIn("-i", cmd)
        self.assertIn(str(icon), cmd)
        self.assertEqual(cmd[-2:], ["Fireraven", "hello"])

    def test_linux_toast_without_icon(self) -> None:
        from core.unavailable_notice import _linux_toast

        with mock.patch("core.unavailable_notice.shutil.which", return_value="/usr/bin/notify-send"):
            with mock.patch("core.unavailable_notice.subprocess.Popen") as popen:
                _linux_toast("hello")
        cmd = popen.call_args.args[0]
        self.assertNotIn("-i", cmd)
        self.assertEqual(cmd[-2:], ["Fireraven", "hello"])

    def test_windows_toast_fires_action_center_only(self) -> None:
        from core.unavailable_notice import _windows_toast

        self._place_icon()
        with mock.patch("core.unavailable_notice.subprocess.Popen") as popen:
            _windows_toast("hello")
        self.assertEqual(popen.call_count, 1)
        toast_argv = popen.call_args.args[0]
        self.assertEqual(toast_argv[0], "powershell")
        self.assertIn("-File", toast_argv)
        toast_path = Path(toast_argv[-1])
        self.assertTrue(toast_path.is_file())
        toast_script = toast_path.read_text(encoding="utf-8")
        self.assertIn("ToastNotification", toast_script)
        self.assertIn("ToastGeneric", toast_script)
        self.assertIn("hello", toast_script)
        self.assertIn("Fireraven", toast_script)
        self.assertIn("Fireraven.FireGuard", toast_script)
        self.assertNotIn("1AC14E77-02E7-4E5D-B744-2EB1AE5198B7", toast_script)
        self.assertIn("Start-Sleep", toast_script)
        self.assertNotIn("MessageBoxTimeoutW", toast_script)
        self.assertNotIn("NotifyIcon", toast_script)
        toast_path.unlink(missing_ok=True)
        kwargs = popen.call_args.kwargs
        self.assertIs(kwargs.get("stdout"), subprocess.DEVNULL)
        self.assertIs(kwargs.get("stderr"), subprocess.DEVNULL)
        self.assertIs(kwargs.get("stdin"), subprocess.DEVNULL)
        self.assertTrue(kwargs.get("close_fds"))
        flags = kwargs.get("creationflags", 0)
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            self.assertTrue(flags & subprocess.CREATE_NO_WINDOW)
        if hasattr(subprocess, "DETACHED_PROCESS"):
            self.assertFalse(flags & subprocess.DETACHED_PROCESS)

    def test_windows_action_center_xml_escapes_special_chars(self) -> None:
        from core.unavailable_notice import _windows_toast

        tricky = 'A & B <C> "D" \'E\''
        with mock.patch("core.unavailable_notice.subprocess.Popen") as popen:
            _windows_toast(tricky)
        toast_path = Path(popen.call_args.args[0][-1])
        toast_script = toast_path.read_text(encoding="utf-8")
        toast_path.unlink(missing_ok=True)
        self.assertIn("&amp;", toast_script)
        self.assertIn("&lt;", toast_script)
        self.assertIn("&gt;", toast_script)
        self.assertIn("&quot;", toast_script)
        self.assertIn("&apos;", toast_script)
        self.assertIn("ToastGeneric", toast_script)


if __name__ == "__main__":
    unittest.main()
