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
    "run_cursor_guardrail.ps1|claude_guardrail.py|fireraven_input_guardrail.py"
)
CURSOR_EVENTS = "beforeSubmitPrompt beforeShellExecution beforeMCPExecution beforeReadFile"


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


if __name__ == "__main__":
    unittest.main()
