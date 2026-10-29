from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.guardrail import GuardrailError
from core.secured_notice import SECURED_MESSAGE, consume_secured_notice, emit_secured_notice
from core.unavailable_notice import UNAVAILABLE_MESSAGE


class SecuredNoticeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self._hooks_root = Path(self._tmpdir.name)
        self._patcher = mock.patch("core.session_store.hooks_root", return_value=self._hooks_root)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def test_consume_once_then_none(self) -> None:
        first = consume_secured_notice("sess-1")
        second = consume_secured_notice("sess-1")
        self.assertEqual(first, SECURED_MESSAGE)
        self.assertIsNone(second)

    def test_consume_empty_session_id(self) -> None:
        first = consume_secured_notice("")
        second = consume_secured_notice("")
        self.assertEqual(first, SECURED_MESSAGE)
        self.assertIsNone(second)

    def test_emit_toasts_once(self) -> None:
        with mock.patch("core.secured_notice.show_unavailable_toast") as toast:
            first = emit_secured_notice("sess-toast")
            second = emit_secured_notice("sess-toast")
        self.assertEqual(first, SECURED_MESSAGE)
        self.assertIsNone(second)
        toast.assert_called_once_with(SECURED_MESSAGE)


class CursorSecuredNoticeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self._hooks_root = Path(self._tmpdir.name)
        self._patcher = mock.patch("core.session_store.hooks_root", return_value=self._hooks_root)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def _run_cursor(
        self,
        *,
        side_effect: Exception | None = None,
        toast_mock: mock.MagicMock | None = None,
    ) -> str:
        from adapters import cursor as cursor_adapter

        payload = {
            "hook_event_name": "beforeSubmitPrompt",
            "conversation_id": "cursor-secured",
            "prompt": "hello",
        }
        toast_patch = mock.patch(
            "core.secured_notice.show_unavailable_toast",
            toast_mock if toast_mock is not None else mock.DEFAULT,
        )
        with mock.patch.object(cursor_adapter, "read_hook_input", return_value=payload):
            with mock.patch.object(cursor_adapter, "load_config", return_value={}):
                with mock.patch.object(
                    cursor_adapter,
                    "resolve_settings",
                    return_value={"fail_closed": False},
                ):
                    check_kw: dict = {}
                    if side_effect is not None:
                        check_kw["side_effect"] = side_effect
                    else:
                        check_kw["return_value"] = {"is_safe": True}
                    with mock.patch.object(cursor_adapter, "run_input_check", **check_kw):
                        # Fail-open path still uses unavailable_notice toast; patch both.
                        with mock.patch("core.unavailable_notice.show_unavailable_toast"):
                            with toast_patch as toast:
                                if toast_mock is None:
                                    toast_mock = toast
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

    def test_first_success_includes_secured_message_and_toasts(self) -> None:
        toast = mock.MagicMock()
        first = json.loads(self._run_cursor(toast_mock=toast))
        self.assertTrue(first.get("continue"))
        self.assertEqual(first.get("user_message"), SECURED_MESSAGE)
        toast.assert_called_once_with(SECURED_MESSAGE)

        second = json.loads(self._run_cursor(toast_mock=toast))
        self.assertTrue(second.get("continue"))
        self.assertNotIn("user_message", second)
        toast.assert_called_once_with(SECURED_MESSAGE)

    def test_fail_open_does_not_use_secured_message(self) -> None:
        payload = json.loads(self._run_cursor(side_effect=RuntimeError("HTTP 503")))
        self.assertTrue(payload.get("continue"))
        self.assertEqual(payload.get("user_message"), UNAVAILABLE_MESSAGE)
        self.assertNotEqual(payload.get("user_message"), SECURED_MESSAGE)

    def test_deny_does_not_use_secured_message(self) -> None:
        payload = json.loads(
            self._run_cursor(side_effect=GuardrailError("blocked by policy"))
        )
        self.assertFalse(payload.get("continue"))
        self.assertNotEqual(payload.get("user_message"), SECURED_MESSAGE)

    def test_shell_allow_stays_quiet(self) -> None:
        from adapters import cursor as cursor_adapter

        payload = {
            "hook_event_name": "beforeShellExecution",
            "conversation_id": "cursor-secured-shell",
            "command": "echo hi",
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
                        return_value={"is_safe": True},
                    ):
                        with mock.patch("builtins.print") as printer:
                            with self.assertRaises(SystemExit) as cm:
                                cursor_adapter.main()
        self.assertEqual(cm.exception.code, 0)
        out = json.loads(printer.call_args.args[0])
        self.assertEqual(out.get("permission"), "allow")
        self.assertNotIn("user_message", out)


if __name__ == "__main__":
    unittest.main()
