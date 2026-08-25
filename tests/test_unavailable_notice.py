from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.unavailable_notice import (
    UNAVAILABLE_MESSAGE,
    consume_unavailable_notice,
    emit_unavailable_notice,
)


class UnavailableNoticeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self._hooks_root = Path(self._tmpdir.name)
        self._patcher = mock.patch("core.session_store.hooks_root", return_value=self._hooks_root)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def test_consume_once_then_none(self) -> None:
        first = consume_unavailable_notice("sess-1")
        second = consume_unavailable_notice("sess-1")
        self.assertEqual(first, UNAVAILABLE_MESSAGE)
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


class CursorFailOpenNoticeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self._hooks_root = Path(self._tmpdir.name)
        self._patcher = mock.patch("core.session_store.hooks_root", return_value=self._hooks_root)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def test_fail_open_includes_user_message_once(self) -> None:
        from adapters import cursor as cursor_adapter

        payload = {
            "hook_event_name": "beforeSubmitPrompt",
            "conversation_id": "cursor-sess",
            "prompt": "hello",
        }

        def run_once() -> str:
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
                            side_effect=RuntimeError("HTTP 503"),
                        ):
                            with mock.patch(
                                "core.unavailable_notice.show_unavailable_toast",
                            ):
                                with mock.patch("builtins.print") as printer:
                                    with self.assertRaises(SystemExit) as cm:
                                        cursor_adapter.main()
            self.assertEqual(cm.exception.code, 0)
            # First print may be stderr audit from emit; find continue:true stdout
            stdout_calls = [
                c.args[0]
                for c in printer.call_args_list
                if c.args and isinstance(c.args[0], str) and "continue" in c.args[0]
            ]
            self.assertTrue(stdout_calls)
            return stdout_calls[-1]

        first_out = run_once()
        first_payload = json.loads(first_out)
        self.assertTrue(first_payload.get("continue"))
        self.assertEqual(first_payload.get("user_message"), UNAVAILABLE_MESSAGE)

        second_out = run_once()
        second_payload = json.loads(second_out)
        self.assertTrue(second_payload.get("continue"))
        self.assertNotIn("user_message", second_payload)


if __name__ == "__main__":
    unittest.main()
