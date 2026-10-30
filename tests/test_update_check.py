from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core import update_check


class ResolveChannelTests(unittest.TestCase):
    def test_github_default(self) -> None:
        ch = update_check.resolve_channel(None, env={})
        self.assertEqual(ch["channel"], "github")
        self.assertIn("raw.githubusercontent.com", ch["raw_base"])

    def test_gitlab_project_env(self) -> None:
        ch = update_check.resolve_channel(
            None,
            env={
                "FIRERAVEN_HOOKS_GITLAB_PROJECT": "fireravenai/fireraven-agent-hooks",
                "FIRERAVEN_HOOKS_REF": "dev",
            },
        )
        self.assertEqual(ch["channel"], "gitlab_api")
        self.assertEqual(ch["project"], "fireravenai/fireraven-agent-hooks")
        self.assertEqual(ch["ref"], "dev")
        self.assertEqual(ch["gitlab_host"], "https://gitlab.com")

    def test_parse_raw_base_to_gitlab_api(self) -> None:
        ch = update_check.resolve_channel(
            {},
            env={"FIRERAVEN_HOOKS_RAW_BASE": "https://gitlab.com/g/p/-/raw/dev/"},
        )
        self.assertEqual(ch["channel"], "gitlab_api")
        self.assertEqual(ch["project"], "g/p")
        self.assertEqual(ch["ref"], "dev")
        self.assertEqual(ch["gitlab_host"], "https://gitlab.com")

    def test_meta_gitlab_api(self) -> None:
        ch = update_check.resolve_channel(
            {
                "channel": "gitlab_api",
                "gitlab_host": "https://gitlab.com",
                "project": "g/p",
                "ref": "dev",
            },
            env={},
        )
        self.assertEqual(ch["channel"], "gitlab_api")
        self.assertEqual(ch["project"], "g/p")

    def test_opaque_raw_base_stays_path_join(self) -> None:
        ch = update_check.resolve_channel(
            {},
            env={"FIRERAVEN_HOOKS_RAW_BASE": "https://example.com/raw/main"},
        )
        self.assertEqual(ch["channel"], "github")
        self.assertEqual(ch["raw_base"], "https://example.com/raw/main")


class FileUrlTests(unittest.TestCase):
    def test_gitlab_encodes_project_and_path(self) -> None:
        ch = {
            "channel": "gitlab_api",
            "gitlab_host": "https://gitlab.com",
            "project": "fireravenai/fireraven-agent-hooks",
            "ref": "dev",
            "raw_base": "",
        }
        url = update_check.file_url(ch, "core/update_check.py")
        self.assertIn("fireravenai%2Ffireraven-agent-hooks", url)
        self.assertIn("core%2Fupdate_check.py", url)
        self.assertIn("raw?ref=dev", url)
        self.assertTrue(url.startswith("https://gitlab.com/api/v4/projects/"))

    def test_github_path_join(self) -> None:
        ch = {
            "channel": "github",
            "raw_base": "https://raw.githubusercontent.com/o/r/refs/heads/main",
            "gitlab_host": "",
            "project": "",
            "ref": "main",
        }
        self.assertEqual(
            update_check.file_url(ch, "VERSION"),
            "https://raw.githubusercontent.com/o/r/refs/heads/main/VERSION",
        )


class IntervalTests(unittest.TestCase):
    def test_github_default_six_hours(self) -> None:
        sec = update_check.resolve_check_interval_sec(
            {"channel": "github", "raw_base": "https://raw.githubusercontent.com/o/r/refs/heads/main"},
            env={},
            config={},
        )
        self.assertEqual(sec, update_check.GITHUB_INTERVAL_SEC)

    def test_gitlab_five_minutes(self) -> None:
        sec = update_check.resolve_check_interval_sec(
            {"channel": "gitlab_api", "gitlab_host": "https://gitlab.com"},
            env={},
            config={},
        )
        self.assertEqual(sec, update_check.GITLAB_INTERVAL_SEC)

    def test_env_override(self) -> None:
        sec = update_check.resolve_check_interval_sec(
            {"channel": "gitlab_api"},
            env={"FIRERAVEN_UPDATE_CHECK_INTERVAL_SEC": "60"},
            config={},
        )
        self.assertEqual(sec, 60)


class SemverTests(unittest.TestCase):
    def test_newer(self) -> None:
        self.assertTrue(update_check.is_newer("0.2.0", "0.1.0"))
        self.assertFalse(update_check.is_newer("0.1.0", "0.2.0"))

    def test_parse_strips_v(self) -> None:
        self.assertEqual(update_check.parse_semver("v1.2.3"), (1, 2, 3))


class ApplyPreviewTests(unittest.TestCase):
    def test_gitlab_apply_uses_api_and_token_header(self) -> None:
        ch = {
            "channel": "gitlab_api",
            "gitlab_host": "https://gitlab.com",
            "project": "g/p",
            "ref": "dev",
            "raw_base": "",
        }
        cmd = update_check.apply_command_preview(ch, "all")
        self.assertIn("PRIVATE-TOKEN", cmd)
        self.assertIn("api/v4/projects/", cmd)
        self.assertIn("install.sh", cmd)
        self.assertIn("--agent all", cmd)

    def test_github_apply_path_join(self) -> None:
        ch = {
            "channel": "github",
            "raw_base": "https://raw.githubusercontent.com/o/r/refs/heads/main",
            "gitlab_host": "",
            "project": "",
            "ref": "main",
        }
        cmd = update_check.apply_command_preview(ch, "cursor")
        self.assertIn("https://raw.githubusercontent.com/o/r/refs/heads/main/install.sh", cmd)
        self.assertNotIn("PRIVATE-TOKEN", cmd)


class FetchAuthTests(unittest.TestCase):
    def test_fetch_sends_private_token(self) -> None:
        ch = {
            "channel": "gitlab_api",
            "gitlab_host": "https://gitlab.com",
            "project": "g/p",
            "ref": "dev",
            "raw_base": "",
        }
        with mock.patch.object(update_check, "_http_get", return_value="0.2.0\n") as http:
            ver = update_check._fetch_remote_version(
                ch, config={"FIRERAVEN_HOOKS_TOKEN": "glpat-test"}
            )
            self.assertEqual(ver, "0.2.0")
            http.assert_called_once()
            _args, kwargs = http.call_args
            self.assertEqual(kwargs.get("token"), "glpat-test")
            self.assertIn("api/v4/projects/", _args[0])


class MaybePromptUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name)
        (self.root / "VERSION").write_text("0.1.0\n", encoding="utf-8")
        (self.root / "install_meta.json").write_text(
            json.dumps(
                {
                    "agents": "cursor",
                    "channel": "gitlab_api",
                    "gitlab_host": "https://gitlab.com",
                    "project": "g/p",
                    "ref": "dev",
                    "raw_base": "",
                }
            ),
            encoding="utf-8",
        )
        self._hooks = mock.patch("core.update_check.hooks_root", return_value=self.root)
        self._hooks.start()
        self._load = mock.patch(
            "core.update_check.load_config",
            return_value={"FIRERAVEN_HOOKS_TOKEN": "glpat-test"},
        )
        self._load.start()

    def tearDown(self) -> None:
        self._hooks.stop()
        self._load.stop()
        self._tmpdir.cleanup()

    def test_disabled_skips(self) -> None:
        with mock.patch(
            "core.update_check.load_config",
            return_value={"FIRERAVEN_UPDATE_CHECK": "0", "FIRERAVEN_HOOKS_TOKEN": "t"},
        ):
            with mock.patch.object(update_check, "_fetch_remote_version") as fetch:
                update_check.maybe_prompt_update()
                fetch.assert_not_called()

    def test_missing_token_soft_fails(self) -> None:
        with mock.patch("core.update_check.load_config", return_value={}):
            with mock.patch.object(update_check, "_fetch_remote_version") as fetch:
                with mock.patch.object(update_check, "request_update_dialog") as dialog:
                    update_check.maybe_prompt_update()
                    fetch.assert_not_called()
                    dialog.assert_not_called()

    def test_throttle_skips_network(self) -> None:
        import time

        state = {"last_check_unix": int(time.time()), "snoozed_version": None}
        (self.root / ".update_state.json").write_text(json.dumps(state), encoding="utf-8")
        with mock.patch.object(update_check, "_fetch_remote_version") as fetch:
            update_check.maybe_prompt_update()
            fetch.assert_not_called()

    def test_newer_version_toasts_and_later_snoozes(self) -> None:
        with mock.patch.object(update_check, "_fetch_remote_version", return_value="0.2.0"):
            with mock.patch.object(update_check, "show_unavailable_toast") as toast:
                with mock.patch.object(
                    update_check, "request_update_dialog", return_value="later"
                ) as dialog:
                    with mock.patch.object(update_check, "_apply_update") as apply:
                        update_check.maybe_prompt_update()
                        toast.assert_called_once()
                        dialog.assert_called_once()
                        apply.assert_not_called()
        state = json.loads((self.root / ".update_state.json").read_text(encoding="utf-8"))
        self.assertEqual(state.get("snoozed_version"), "0.2.0")

    def test_bom_meta_allow_uses_recorded_agent(self) -> None:
        payload = json.dumps(
            {
                "agents": "cursor",
                "channel": "github",
                "raw_base": "https://example.invalid/raw",
                "repo": "o/r",
                "ref": "main",
            }
        )
        (self.root / "install_meta.json").write_bytes(b"\xef\xbb\xbf" + payload.encode("utf-8"))
        with mock.patch.object(update_check, "_fetch_remote_version", return_value="0.2.0"):
            with mock.patch.object(update_check, "show_unavailable_toast"):
                with mock.patch.object(
                    update_check, "request_update_dialog", return_value="allow"
                ):
                    with mock.patch.object(
                        update_check, "_apply_update", return_value=True
                    ) as apply:
                        update_check.maybe_prompt_update()
                        apply.assert_called_once()
                        self.assertEqual(apply.call_args.args[1], "cursor")

    def test_allow_applies_with_channel(self) -> None:
        with mock.patch.object(update_check, "_fetch_remote_version", return_value="0.2.0"):
            with mock.patch.object(update_check, "show_unavailable_toast") as toast:
                with mock.patch.object(
                    update_check, "request_update_dialog", return_value="allow"
                ):
                    with mock.patch.object(
                        update_check, "_apply_update", return_value=True
                    ) as apply:
                        update_check.maybe_prompt_update()
                        apply.assert_called_once()
                        args, kwargs = apply.call_args
                        self.assertEqual(args[0]["channel"], "gitlab_api")
                        self.assertEqual(args[0]["project"], "g/p")
                        self.assertEqual(args[1], "cursor")
                        self.assertIn("config", kwargs)
                        self.assertEqual(kwargs.get("expected_version"), "0.2.0")
        messages = [c.args[0] for c in toast.call_args_list]
        self.assertTrue(any("update available" in m for m in messages))
        self.assertTrue(any("Updating Fireraven hooks to 0.2.0" in m for m in messages))
        self.assertTrue(any("updated to 0.2.0" in m for m in messages))
        state = json.loads((self.root / ".update_state.json").read_text(encoding="utf-8"))
        self.assertIsNone(state.get("snoozed_version"))

    def test_allow_apply_failure_toasts_log_path(self) -> None:
        with mock.patch.object(update_check, "_fetch_remote_version", return_value="0.2.0"):
            with mock.patch.object(update_check, "show_unavailable_toast") as toast:
                with mock.patch.object(
                    update_check, "request_update_dialog", return_value="allow"
                ):
                    with mock.patch.object(
                        update_check, "_apply_update", return_value=False
                    ):
                        update_check.maybe_prompt_update()
        messages = [c.args[0] for c in toast.call_args_list]
        self.assertTrue(any("Updating Fireraven hooks to 0.2.0" in m for m in messages))
        fail = [m for m in messages if "update failed" in m]
        self.assertEqual(len(fail), 1)
        self.assertIn("update.log", fail[0])

    def test_snoozed_same_version_skips_dialog(self) -> None:
        import time

        (self.root / ".update_state.json").write_text(
            json.dumps({"last_check_unix": 0, "snoozed_version": "0.2.0"}),
            encoding="utf-8",
        )
        with mock.patch.object(update_check, "_fetch_remote_version", return_value="0.2.0"):
            with mock.patch.object(update_check, "request_update_dialog") as dialog:
                with mock.patch("core.update_check.time.time", return_value=time.time()):
                    update_check.maybe_prompt_update()
                    dialog.assert_not_called()


class ApplyUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name)
        (self.root / "VERSION").write_text("0.1.0\n", encoding="utf-8")
        self.channel = {
            "channel": "github",
            "raw_base": "https://raw.githubusercontent.com/o/r/refs/heads/main",
            "gitlab_host": "",
            "project": "",
            "ref": "main",
        }

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_nonzero_exit_writes_log_and_fails(self) -> None:
        result = mock.Mock(returncode=1, stdout="", stderr="boom\n")
        with mock.patch.object(update_check.subprocess, "run", return_value=result):
            ok = update_check._apply_update(
                self.channel,
                "cursor",
                config={},
                expected_version="0.2.0",
                root=self.root,
            )
        self.assertFalse(ok)
        log = (self.root / "state" / "update.log").read_text(encoding="utf-8")
        self.assertIn("boom", log)

    def test_zero_exit_and_version_match_succeeds(self) -> None:
        def _fake_run(*_a, **_k):
            (self.root / "VERSION").write_text("0.2.0\n", encoding="utf-8")
            return mock.Mock(returncode=0, stdout="[INFO] ok\n", stderr="")

        with mock.patch.object(update_check.subprocess, "run", side_effect=_fake_run):
            ok = update_check._apply_update(
                self.channel,
                "cursor",
                config={},
                expected_version="0.2.0",
                root=self.root,
            )
        self.assertTrue(ok)
        log = (self.root / "state" / "update.log").read_text(encoding="utf-8")
        self.assertIn("[INFO] ok", log)

    def test_zero_exit_version_mismatch_fails(self) -> None:
        result = mock.Mock(returncode=0, stdout="done\n", stderr="")
        with mock.patch.object(update_check.subprocess, "run", return_value=result):
            ok = update_check._apply_update(
                self.channel,
                "cursor",
                config={},
                expected_version="0.2.0",
                root=self.root,
            )
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
