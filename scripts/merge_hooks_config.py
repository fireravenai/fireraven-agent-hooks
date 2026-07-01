#!/usr/bin/env python3
"""Merge or scrub Fireraven hook entries in JSONC agent config files."""

from __future__ import annotations

import argparse
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
  sys.path.insert(0, _SCRIPT_DIR)

from jsonc_modify import JsoncModifyError, merge_hook_array, scrub_hook_array, write_jsonc_file


def _read_text(path: str) -> str:
  if not os.path.isfile(path) or os.path.getsize(path) == 0:
    return ""
  with open(path, encoding="utf-8") as handle:
    return handle.read()


def _default_cursor_document() -> str:
  return '{\n  "version": 1,\n  "hooks": {}\n}\n'


def _default_windsurf_document() -> str:
  return '{\n  "hooks": {}\n}\n'


def _default_claude_document() -> str:
  return '{\n  "hooks": {}\n}\n'


def _ensure_parent(path: str) -> None:
  parent = os.path.dirname(path)
  if parent:
    os.makedirs(parent, exist_ok=True)


def _fail(path: str, exc: Exception) -> None:
  print(
    f"[ERROR] Could not parse {path} (invalid JSONC).\n"
    f"        Fix syntax errors in the file, then re-run the installer.\n"
    f"        Details: {exc}",
    file=sys.stderr,
  )
  sys.exit(1)


def _merge_events(
  path: str,
  text: str,
  events: list[str],
  entry: dict,
  owned_markers: list[str],
  default_document: str,
) -> None:
  if not text.strip():
    text = default_document
  for event in events:
    try:
      text = merge_hook_array(text, ["hooks", event], entry, owned_markers)
    except JsoncModifyError as exc:
      _fail(path, exc)
  write_jsonc_file(path, text)


def _scrub_events(path: str, text: str, events: list[str], owned_markers: list[str]) -> None:
  if not text.strip():
    return
  for event in events:
    try:
      text = scrub_hook_array(text, ["hooks", event], owned_markers)
    except JsoncModifyError as exc:
      _fail(path, exc)
  write_jsonc_file(path, text)


def cmd_merge_windsurf(args: argparse.Namespace) -> None:
  _ensure_parent(args.path)
  entry = {"command": f"python3 {args.script_path}"}
  if args.powershell_command:
    entry["powershell"] = args.powershell_command
  _merge_events(
    args.path,
    _read_text(args.path),
    args.events.split(),
    entry,
    args.owned_pattern.split("|"),
    _default_windsurf_document(),
  )


def cmd_merge_cursor(args: argparse.Namespace) -> None:
  _ensure_parent(args.path)
  entry = {"command": args.command or f"python3 {args.script_path}"}
  _merge_events(
    args.path,
    _read_text(args.path),
    args.events.split(),
    entry,
    args.owned_pattern.split("|"),
    _default_cursor_document(),
  )


def cmd_merge_claude(args: argparse.Namespace) -> None:
  _ensure_parent(args.path)
  command = args.command or f"python3 {args.script_path}"
  entry = {
    "matcher": ".*",
    "hooks": [{"type": "command", "command": command}],
  }
  _merge_events(
    args.path,
    _read_text(args.path),
    ["PreToolUse"],
    entry,
    ["fireraven"],
    _default_claude_document(),
  )


def cmd_scrub_windsurf(args: argparse.Namespace) -> None:
  _scrub_events(args.path, _read_text(args.path), args.events.split(), args.owned_pattern.split("|"))


def cmd_scrub_cursor(args: argparse.Namespace) -> None:
  _scrub_events(args.path, _read_text(args.path), args.events.split(), args.owned_pattern.split("|"))


def cmd_scrub_claude(args: argparse.Namespace) -> None:
  _scrub_events(args.path, _read_text(args.path), ["PreToolUse"], args.owned_pattern.split("|"))


def build_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(description="Merge or scrub Fireraven hooks in JSONC config files")
  sub = parser.add_subparsers(dest="command", required=True)

  def add_common_merge_flags(command: argparse.ArgumentParser) -> None:
    command.add_argument("--path", required=True)
    command.add_argument("--owned-pattern", required=True)

  merge_windsurf = sub.add_parser("merge-windsurf")
  add_common_merge_flags(merge_windsurf)
  merge_windsurf.add_argument("--script-path", required=True)
  merge_windsurf.add_argument("--events", required=True)
  merge_windsurf.add_argument("--powershell-command", default="")
  merge_windsurf.set_defaults(func=cmd_merge_windsurf)

  merge_cursor = sub.add_parser("merge-cursor")
  add_common_merge_flags(merge_cursor)
  merge_cursor.add_argument("--script-path", required=True)
  merge_cursor.add_argument("--events", required=True)
  merge_cursor.add_argument("--command", default="")
  merge_cursor.set_defaults(func=cmd_merge_cursor)

  merge_claude = sub.add_parser("merge-claude")
  merge_claude.add_argument("--path", required=True)
  merge_claude.add_argument("--script-path", required=True)
  merge_claude.add_argument("--command", default="")
  merge_claude.set_defaults(func=cmd_merge_claude)

  scrub_windsurf = sub.add_parser("scrub-windsurf")
  scrub_windsurf.add_argument("--path", required=True)
  scrub_windsurf.add_argument("--events", required=True)
  scrub_windsurf.add_argument("--owned-pattern", required=True)
  scrub_windsurf.set_defaults(func=cmd_scrub_windsurf)

  scrub_cursor = sub.add_parser("scrub-cursor")
  scrub_cursor.add_argument("--path", required=True)
  scrub_cursor.add_argument("--events", required=True)
  scrub_cursor.add_argument("--owned-pattern", required=True)
  scrub_cursor.set_defaults(func=cmd_scrub_cursor)

  scrub_claude = sub.add_parser("scrub-claude")
  scrub_claude.add_argument("--path", required=True)
  scrub_claude.add_argument("--owned-pattern", required=True)
  scrub_claude.set_defaults(func=cmd_scrub_claude)

  return parser


def main(argv: list[str] | None = None) -> None:
  parser = build_parser()
  args = parser.parse_args(argv)
  args.func(args)


if __name__ == "__main__":
  main()
