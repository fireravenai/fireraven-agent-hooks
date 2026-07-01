"""JSONC surgical edits preserving comments and formatting.

Edit algorithm derived from microsoft/node-jsonc-parser (MIT).
JSONC format per https://jsonc.org/
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable


class JsoncModifyError(Exception):
    """Raised when JSONC cannot be parsed or modified."""


@dataclass(frozen=True)
class Edit:
    offset: int
    length: int
    content: str


@dataclass
class Node:
    kind: str
    value: Any
    start: int
    end: int
    children: list[Any] | None = None


def apply_edits(text: str, edits: list[Edit]) -> str:
  """Apply non-overlapping edits from highest offset to lowest."""
  if not edits:
    return text
  ordered = sorted(edits, key=lambda e: e.offset, reverse=True)
  result = text
  for edit in ordered:
    result = result[: edit.offset] + edit.content + result[edit.offset + edit.length :]
  return result


def _skip_ws_and_comments(text: str, index: int) -> int:
  length = len(text)
  while index < length:
    ch = text[index]
    if ch in " \t\n\r":
      index += 1
      continue
    if text.startswith("//", index):
      index += 2
      while index < length and text[index] != "\n":
        index += 1
      continue
    if text.startswith("/*", index):
      end = text.find("*/", index + 2)
      if end == -1:
        raise JsoncModifyError("Unterminated block comment")
      index = end + 2
      continue
    break
  return index


def _parse_string(text: str, index: int) -> tuple[str, int]:
  if text[index] != '"':
    raise JsoncModifyError(f"Expected string at offset {index}")
  index += 1
  chars: list[str] = []
  while index < len(text):
    ch = text[index]
    if ch == '"':
      return "".join(chars), index + 1
    if ch == "\\":
      index += 1
      if index >= len(text):
        raise JsoncModifyError("Unterminated string escape")
      esc = text[index]
      if esc in '"\\/bfnrt':
        mapping = {"b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}
        chars.append(mapping.get(esc, esc))
      elif esc == "u":
        if index + 4 >= len(text):
          raise JsoncModifyError("Invalid unicode escape")
        chars.append(chr(int(text[index + 1 : index + 5], 16)))
        index += 4
      else:
        chars.append(esc)
      index += 1
      continue
    chars.append(ch)
    index += 1
  raise JsoncModifyError("Unterminated string")


def _parse_literal(text: str, index: int, literal: str, value: Any) -> tuple[Any, int]:
  if not text.startswith(literal, index):
    raise JsoncModifyError(f"Expected {literal} at offset {index}")
  return value, index + len(literal)


def _parse_number(text: str, index: int) -> tuple[float | int, int]:
  start = index
  if text[index] == "-":
    index += 1
  while index < len(text) and text[index].isdigit():
    index += 1
  if index < len(text) and text[index] == ".":
    index += 1
    while index < len(text) and text[index].isdigit():
      index += 1
  if index < len(text) and text[index] in "eE":
    index += 1
    if index < len(text) and text[index] in "+-":
      index += 1
    while index < len(text) and text[index].isdigit():
      index += 1
  number_text = text[start:index]
  if "." in number_text or "e" in number_text or "E" in number_text:
    return float(number_text), index
  return int(number_text), index


def _parse_value(text: str, index: int) -> tuple[Node, int]:
  index = _skip_ws_and_comments(text, index)
  start = index
  ch = text[index]
  if ch == "{":
    return _parse_object(text, index)
  if ch == "[":
    return _parse_array(text, index)
  if ch == '"':
    string_value, next_index = _parse_string(text, index)
    return Node("string", string_value, start, next_index), next_index
  if text.startswith("true", index):
    value, next_index = _parse_literal(text, index, "true", True)
    return Node("bool", value, start, next_index), next_index
  if text.startswith("false", index):
    value, next_index = _parse_literal(text, index, "false", False)
    return Node("bool", value, start, next_index), next_index
  if text.startswith("null", index):
    value, next_index = _parse_literal(text, index, "null", None)
    return Node("null", value, start, next_index), next_index
  if ch in "-0123456789":
    number, next_index = _parse_number(text, index)
    return Node("number", number, start, next_index), next_index
  raise JsoncModifyError(f"Unexpected character {ch!r} at offset {index}")


def _parse_object(text: str, index: int) -> tuple[Node, int]:
  start = index
  if text[index] != "{":
    raise JsoncModifyError("Expected object")
  index += 1
  children: list[tuple[Node, Node]] = []
  index = _skip_ws_and_comments(text, index)
  if text.startswith("}", index):
    return Node("object", {}, start, index + 1, children), index + 1
  while True:
    index = _skip_ws_and_comments(text, index)
    key, index = _parse_string(text, index)
    key_node = Node("string", key, index - len(key) - 2, index)
    index = _skip_ws_and_comments(text, index)
    if text[index] != ":":
      raise JsoncModifyError("Expected ':' after object key")
    index += 1
    value_node, index = _parse_value(text, index)
    children.append((key_node, value_node))
    index = _skip_ws_and_comments(text, index)
    if text.startswith("}", index):
      return Node("object", None, start, index + 1, children), index + 1
    if text[index] != ",":
      raise JsoncModifyError("Expected ',' or '}' in object")
    index += 1


def _parse_array(text: str, index: int) -> tuple[Node, int]:
  start = index
  if text[index] != "[":
    raise JsoncModifyError("Expected array")
  index += 1
  children: list[Node] = []
  index = _skip_ws_and_comments(text, index)
  if text.startswith("]", index):
    return Node("array", [], start, index + 1, children), index + 1
  while True:
    item, index = _parse_value(text, index)
    children.append(item)
    index = _skip_ws_and_comments(text, index)
    if text.startswith("]", index):
      return Node("array", None, start, index + 1, children), index + 1
    if text[index] != ",":
      raise JsoncModifyError("Expected ',' or ']' in array")
    index += 1


def parse_tree(text: str) -> Node:
  stripped = text.strip()
  if not stripped:
    raise JsoncModifyError("Empty document")
  node, end = _parse_value(text, 0)
  end = _skip_ws_and_comments(text, end)
  if end != len(text):
    raise JsoncModifyError(f"Unexpected content at offset {end}")
  return node


def _node_to_value(node: Node) -> Any:
  if node.kind == "object":
    result: dict[str, Any] = {}
    for key_node, value_node in node.children or []:
      result[str(key_node.value)] = _node_to_value(value_node)
    return result
  if node.kind == "array":
    return [_node_to_value(child) for child in node.children or []]
  return node.value


def find_node_at_path(root: Node, path: list[str]) -> Node | None:
  current = root
  for segment in path:
    if current.kind != "object" or not current.children:
      return None
    match = None
    for key_node, value_node in current.children:
      if key_node.value == segment:
        match = value_node
        break
    if match is None:
      return None
    current = match
  return current


def _indentation_at(text: str, offset: int) -> str:
  line_start = text.rfind("\n", 0, offset) + 1
  indent = []
  for ch in text[line_start:offset]:
    if ch in " \t":
      indent.append(ch)
    else:
      break
  return "".join(indent) if indent else "  "


def _format_json_value(value: Any, indent: str) -> str:
  return json.dumps(value, indent=2).replace("\n", f"\n{indent}")


def _remove_trailing_comma_ws(text: str, start: int, end: int) -> tuple[int, int]:
  """Expand removal range to include following comma and whitespace."""
  index = end
  while index < len(text) and text[index] in " \t":
    index += 1
  if index < len(text) and text[index] == ",":
    index += 1
    while index < len(text) and text[index] in " \t":
      index += 1
    if index < len(text) and text[index] == "\n":
      index += 1
    return start, index
  # remove leading comma from previous item
  prev = start - 1
  while prev >= 0 and text[prev] in " \t":
    prev -= 1
  if prev >= 0 and text[prev] == ",":
    return prev, end
  return start, end


def remove_array_items(
  text: str,
  root: Node,
  path: list[str],
  predicate: Callable[[str], bool],
) -> tuple[str, list[Edit]]:
  node = find_node_at_path(root, path)
  if node is None or node.kind != "array" or not node.children:
    return text, []

  edits: list[Edit] = []
  for item in reversed(node.children):
    slice_text = text[item.start : item.end]
    if predicate(slice_text):
      start, end = _remove_trailing_comma_ws(text, item.start, item.end)
      edits.append(Edit(start, end - start, ""))
  return text, edits


def append_array_item(
  text: str,
  root: Node,
  path: list[str],
  value: Any,
) -> tuple[str, list[Edit]]:
  node = find_node_at_path(root, path)
  if node is None:
    return text, _insert_object_property(text, root, path, value)

  if node.kind != "array":
    raise JsoncModifyError(f"Path {'.'.join(path)} is not an array")

  indent = _indentation_at(text, node.start + 1)
  item_indent = indent + "  "
  formatted = _format_json_value(value, item_indent)

  if not node.children:
    # Empty array: insert between [ and ]
    insert_at = node.start + 1
    content = f"\n{item_indent}{formatted}\n{indent}"
    return text, [Edit(insert_at, 0, content)]

  last = node.children[-1]
  insert_at = last.end
  content = f",\n{item_indent}{formatted}"
  return text, [Edit(insert_at, 0, content)]


def _insert_object_property(text: str, root: Node, path: list[str], value: Any) -> list[Edit]:
  if len(path) < 2:
    raise JsoncModifyError(f"Cannot create path {'.'.join(path)}")

  parent_path = path[:-1]
  key = path[-1]
  parent = find_node_at_path(root, parent_path)
  if parent is None or parent.kind != "object":
    raise JsoncModifyError(f"Parent path {'.'.join(parent_path)} not found")

  indent = _indentation_at(text, parent.start + 1)
  prop_indent = indent + "  "
  item_indent = prop_indent + "  "
  entry_text = _format_json_value(value, item_indent)
  array_text = f"[\n{item_indent}{entry_text}\n{prop_indent}]"
  property_text = f'\n{prop_indent}"{key}": {array_text}'

  if not parent.children:
    insert_at = parent.start + 1
    return [Edit(insert_at, 0, property_text)]

  last_key, last_value = parent.children[-1]
  insert_at = last_value.end
  return [Edit(insert_at, 0, f",{property_text}")]


def ensure_top_level_version(text: str, root: Node) -> tuple[str, list[Edit]]:
  version_node = find_node_at_path(root, ["version"])
  if version_node is not None:
    return text, []
  if root.kind != "object":
    raise JsoncModifyError("Document root must be an object")
  indent = _indentation_at(text, root.start + 1)
  property_text = f'\n{indent}"version": 1'
  if not root.children:
    return text, [Edit(root.start + 1, 0, property_text)]
  first_key, first_value = root.children[0]
  return text, [Edit(first_value.start, 0, property_text + ",")]


def strip_comments_for_parse(text: str) -> str:
  """Strip JSONC comments for fallback strict-json validation."""
  result: list[str] = []
  index = 0
  in_string = False
  escape = False
  while index < len(text):
    ch = text[index]
    if in_string:
      result.append(ch)
      if escape:
        escape = False
      elif ch == "\\":
        escape = True
      elif ch == '"':
        in_string = False
      index += 1
      continue
    if ch == '"':
      in_string = True
      result.append(ch)
      index += 1
      continue
    if text.startswith("//", index):
      while index < len(text) and text[index] != "\n":
        index += 1
      continue
    if text.startswith("/*", index):
      end = text.find("*/", index + 2)
      if end == -1:
        raise JsoncModifyError("Unterminated block comment")
      index = end + 2
      continue
    result.append(ch)
    index += 1
  return "".join(result)


def entry_matches_markers(entry_text: str, markers: list[str]) -> bool:
  try:
    payload = json.loads(strip_comments_for_parse(entry_text))
  except json.JSONDecodeError:
    return any(marker in entry_text for marker in markers)
  serialized = json.dumps(payload)
  return any(marker in serialized for marker in markers)


def merge_hook_array(
  text: str,
  path: list[str],
  entry: dict[str, Any],
  owned_markers: list[str],
) -> str:
  root = parse_tree(text)
  text, version_edits = ensure_top_level_version(text, root)
  if version_edits:
    text = apply_edits(text, version_edits)
    root = parse_tree(text)

  text, remove_edits = remove_array_items(
    text,
    root,
    path,
    lambda slice_text: entry_matches_markers(slice_text, owned_markers),
  )
  if remove_edits:
    text = apply_edits(text, remove_edits)
    root = parse_tree(text)

  text, append_edits = append_array_item(text, root, path, entry)
  if append_edits:
    text = apply_edits(text, append_edits)
  return text


def scrub_hook_array(
  text: str,
  path: list[str],
  owned_markers: list[str],
) -> str:
  root = parse_tree(text)
  node = find_node_at_path(root, path)
  if node is None or node.kind != "array" or not node.children:
    return text

  text, remove_edits = remove_array_items(
    text,
    root,
    path,
    lambda slice_text: entry_matches_markers(slice_text, owned_markers),
  )
  if not remove_edits:
    return text
  text = apply_edits(text, remove_edits)
  root = parse_tree(text)
  node = find_node_at_path(root, path)
  if node is not None and node.kind == "array" and not node.children:
    return scrub_empty_array_or_property(text, root, path)
  return text


def _property_removal_range(
  text: str,
  key_start: int,
  value_end: int,
  *,
  is_last_child: bool,
) -> tuple[int, int]:
  """Return byte range that removes one object property without breaking siblings."""
  if not is_last_child:
    end = value_end
    while end < len(text) and text[end] in " \t":
      end += 1
    if end < len(text) and text[end] == ",":
      end += 1
    while end < len(text) and text[end] in " \t":
      end += 1
    if end < len(text) and text[end] == "\n":
      end += 1
    line_start = text.rfind("\n", 0, key_start) + 1
    start = line_start if line_start < key_start else key_start
    return start, end

  prev = key_start - 1
  while prev >= 0 and text[prev] in " \t\n\r":
    prev -= 1
  if prev >= 0 and text[prev] == ",":
    start = prev
  else:
    line_start = text.rfind("\n", 0, key_start) + 1
    start = line_start if line_start < key_start else key_start
  return start, value_end


def scrub_empty_array_or_property(text: str, root: Node, path: list[str]) -> str:
  node = find_node_at_path(root, path)
  if node is None:
    return text
  if node.kind == "array" and not node.children:
    parent_path = path[:-1]
    key = path[-1]
    parent = find_node_at_path(root, parent_path)
    if parent is None or parent.kind != "object":
      return text
    children = parent.children or []
    for index, (key_node, value_node) in enumerate(children):
      if key_node.value == key:
        is_last_child = index == len(children) - 1
        start, end = _property_removal_range(
          text,
          key_node.start,
          value_node.end,
          is_last_child=is_last_child,
        )
        return apply_edits(text, [Edit(start, end - start, "")])
  return text


def write_jsonc_file(path: str, text: str) -> None:
  if not text.endswith("\n"):
    text += "\n"
  with open(path, "w", encoding="utf-8", newline="") as handle:
    handle.write(text)
