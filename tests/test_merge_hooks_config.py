"""Tests for JSONC-preserving hook config merge."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "hooks_cursor_with_comments.jsonc"
OWNED_PATTERN = (
    "fireraven|windsurf_guardrail.py|cursor_guardrail.py|"
    "run_cursor_guardrail.ps1|claude_guardrail.py|fireraven_input_guardrail.py|"
    "github_copilot_guardrail.py|run_github_copilot_guardrail.ps1"
)
CURSOR_EVENTS = "beforeSubmitPrompt beforeShellExecution beforeMCPExecution beforeReadFile"
GITHUB_COPILOT_EVENTS = "userPromptSubmitted preToolUse postToolUse"


def _run_merge_cursor(path: Path, script_path: str) -> None:
    subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_DIR / "merge_hooks_config.py"),
            "merge-cursor",
            "--path",
            str(path),
            "--script-path",
            script_path,
            "--events",
            CURSOR_EVENTS,
            "--owned-pattern",
            OWNED_PATTERN,
        ],
        check=True,
        cwd=REPO_ROOT,
    )


def _run_scrub_cursor(path: Path) -> None:
    subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_DIR / "merge_hooks_config.py"),
            "scrub-cursor",
            "--path",
            str(path),
            "--events",
            CURSOR_EVENTS,
            "--owned-pattern",
            OWNED_PATTERN,
        ],
        check=True,
        cwd=REPO_ROOT,
    )


def _run_merge_github_copilot(path: Path, script_path: str) -> None:
    subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_DIR / "merge_hooks_config.py"),
            "merge-github-copilot",
            "--path",
            str(path),
            "--script-path",
            script_path,
            "--events",
            GITHUB_COPILOT_EVENTS,
            "--owned-pattern",
            OWNED_PATTERN,
            "--bash-command",
            f"python3 {script_path}",
            "--powershell-command",
            f"py -3 {script_path}",
        ],
        check=True,
        cwd=REPO_ROOT,
    )


def _run_scrub_github_copilot(path: Path) -> None:
    subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_DIR / "merge_hooks_config.py"),
            "scrub-github-copilot",
            "--path",
            str(path),
            "--events",
            GITHUB_COPILOT_EVENTS,
            "--owned-pattern",
            OWNED_PATTERN,
        ],
        check=True,
        cwd=REPO_ROOT,
    )


def _run_merge_claude(path: Path, script_path: str, command: str = "") -> None:
    args = [
        sys.executable,
        str(SCRIPTS_DIR / "merge_hooks_config.py"),
        "merge-claude",
        "--path",
        str(path),
        "--script-path",
        script_path,
    ]
    if command:
        args.extend(["--command", command])
    subprocess.run(args, check=True, cwd=REPO_ROOT)


def _run_scrub_claude(path: Path) -> None:
    subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_DIR / "merge_hooks_config.py"),
            "scrub-claude",
            "--path",
            str(path),
            "--owned-pattern",
            OWNED_PATTERN,
        ],
        check=True,
        cwd=REPO_ROOT,
    )


def _strip_comments(text: str) -> str:
    sys.path.insert(0, str(SCRIPTS_DIR))
    from jsonc_modify import strip_comments_for_parse

    return strip_comments_for_parse(text)


class MergeHooksConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.hooks_path = Path(self.temp_dir) / "hooks.json"
        shutil.copy(FIXTURE, self.hooks_path)
        self.original = FIXTURE.read_text(encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_preserves_comment_lines(self) -> None:
        _run_merge_cursor(self.hooks_path, "/tmp/cursor_guardrail.py")
        merged = self.hooks_path.read_text(encoding="utf-8")
        for line in self.original.splitlines():
            if line.lstrip().startswith("//"):
                self.assertIn(line, merged)

    def test_registers_active_fireraven_hooks(self) -> None:
        _run_merge_cursor(self.hooks_path, "/tmp/cursor_guardrail.py")
        data = json.loads(_strip_comments(self.hooks_path.read_text(encoding="utf-8")))
        hooks = data["hooks"]
        self.assertEqual(hooks["preToolUse"][0]["command"], "rtk hook cursor")
        for event in CURSOR_EVENTS.split():
            self.assertEqual(len(hooks[event]), 1)
            self.assertIn("cursor_guardrail.py", hooks[event][0]["command"])

    def test_idempotent_merge(self) -> None:
        _run_merge_cursor(self.hooks_path, "/tmp/cursor_guardrail.py")
        first = json.loads(_strip_comments(self.hooks_path.read_text(encoding="utf-8")))
        _run_merge_cursor(self.hooks_path, "/tmp/cursor_guardrail.py")
        second = json.loads(_strip_comments(self.hooks_path.read_text(encoding="utf-8")))
        self.assertEqual(first, second)

    def test_scrub_removes_fireraven_keeps_comments_and_rtk(self) -> None:
        _run_merge_cursor(self.hooks_path, "/tmp/cursor_guardrail.py")
        _run_scrub_cursor(self.hooks_path)
        scrubbed = self.hooks_path.read_text(encoding="utf-8")
        data = json.loads(_strip_comments(scrubbed))
        hooks = data["hooks"]
        self.assertIn("preToolUse", hooks)
        for event in CURSOR_EVENTS.split():
            self.assertNotIn(event, hooks)
        for line in self.original.splitlines():
            if line.lstrip().startswith("//"):
                self.assertIn(line, scrubbed)


class MergeGitHubCopilotHooksConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.hooks_path = Path(self.temp_dir) / "fireraven-fireguard.json"

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_registers_github_copilot_hooks(self) -> None:
        script_path = "/tmp/github_copilot_guardrail.py"
        _run_merge_github_copilot(self.hooks_path, script_path)
        data = json.loads(_strip_comments(self.hooks_path.read_text(encoding="utf-8")))
        hooks = data["hooks"]
        for event in GITHUB_COPILOT_EVENTS.split():
            self.assertEqual(len(hooks[event]), 1)
            entry = hooks[event][0]
            self.assertEqual(entry["type"], "command")
            self.assertIn("github_copilot_guardrail.py", entry["bash"])
            self.assertEqual(entry["timeoutSec"], 45)

    def test_idempotent_merge_and_scrub(self) -> None:
        script_path = "/tmp/github_copilot_guardrail.py"
        _run_merge_github_copilot(self.hooks_path, script_path)
        _run_merge_github_copilot(self.hooks_path, script_path)
        _run_scrub_github_copilot(self.hooks_path)
        data = json.loads(_strip_comments(self.hooks_path.read_text(encoding="utf-8")))
        self.assertEqual(data["hooks"], {})


class MergeClaudeHooksConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.settings_path = Path(self.temp_dir) / "settings.json"

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_registers_pretooluse_and_userpromptsubmit(self) -> None:
        script_path = "/home/user/.claude/hooks/claude_guardrail.py"
        command = f"python3 {script_path}"
        _run_merge_claude(self.settings_path, script_path)

        data = json.loads(_strip_comments(self.settings_path.read_text(encoding="utf-8")))
        hooks = data["hooks"]

        self.assertEqual(len(hooks["PreToolUse"]), 1)
        pretool = hooks["PreToolUse"][0]
        self.assertEqual(pretool["matcher"], ".*")
        self.assertEqual(pretool["hooks"][0]["command"], command)

        self.assertEqual(len(hooks["UserPromptSubmit"]), 1)
        prompt = hooks["UserPromptSubmit"][0]
        self.assertNotIn("matcher", prompt)
        self.assertEqual(prompt["hooks"][0]["command"], command)

    def test_replaces_broken_windows_command(self) -> None:
        script_path = "C:/Users/test/.claude/hooks/claude_guardrail.py"
        broken_command = (
            'powershell -NoProfile -ExecutionPolicy Bypass -Command "$input | & \'py\' \'-3\' '
            "'C:/Users/test/.claude/hooks/claude_guardrail.py'\""
        )
        fixed_command = f"py -3 {script_path}"
        self.settings_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "hooks": {
                        "PreToolUse": [
                            {
                                "matcher": ".*",
                                "hooks": [{"type": "command", "command": broken_command}],
                            }
                        ]
                    },
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        _run_merge_claude(self.settings_path, script_path, command=fixed_command)
        data = json.loads(_strip_comments(self.settings_path.read_text(encoding="utf-8")))

        self.assertEqual(len(data["hooks"]["PreToolUse"]), 1)
        self.assertEqual(data["hooks"]["PreToolUse"][0]["hooks"][0]["command"], fixed_command)
        self.assertEqual(len(data["hooks"]["UserPromptSubmit"]), 1)
        self.assertEqual(data["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"], fixed_command)

    def test_idempotent_merge_and_scrub(self) -> None:
        script_path = "/tmp/claude_guardrail.py"
        _run_merge_claude(self.settings_path, script_path)
        _run_merge_claude(self.settings_path, script_path)
        first = json.loads(_strip_comments(self.settings_path.read_text(encoding="utf-8")))

        _run_scrub_claude(self.settings_path)
        scrubbed = json.loads(_strip_comments(self.settings_path.read_text(encoding="utf-8")))

        self.assertIn("PreToolUse", first["hooks"])
        self.assertIn("UserPromptSubmit", first["hooks"])
        self.assertEqual(scrubbed["hooks"], {})


if __name__ == "__main__":
    unittest.main()
