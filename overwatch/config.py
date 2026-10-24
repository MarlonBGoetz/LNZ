"""Stdlib configuration loaders for gpu-overwatch.

The project must import and test with the Python standard library only, so this
module ships a small YAML parser that covers the exact subset used by the
project's config files (``.overwatch/policy.yaml``, ``.overwatch/project.yaml``)
and the datagen specs. If PyYAML happens to be installed it is used instead; the
built-in parser is a faithful fallback.

Supported YAML subset
----------------------
* ``# comments`` (full-line and trailing, outside quotes)
* mappings with ``key: value`` and nested mappings via indentation
* block sequences with ``- item`` (items may be scalars or inline maps)
* inline flow sequences ``[a, b, c]``
* inline flow mappings ``{a: b, c: d}``
* scalars: ``int``, ``float``, ``bool`` (true/false/yes/no), ``null``/``~``,
  and quoted or bare strings
* empty mapping value (``key:``) yields ``None``

This is intentionally minimal: it does not support anchors, multi-document
streams, block scalars (``|``/``>``), or complex keys.
"""

from __future__ import annotations

import json
import os
from typing import Any, List, Tuple

try:  # Prefer PyYAML when available; never require it.
    import yaml as _pyyaml  # type: ignore
except Exception:  # pragma: no cover - depends on environment
    _pyyaml = None


# --------------------------------------------------------------------------
# Scalar parsing
# --------------------------------------------------------------------------
_BOOL_TRUE = {"true", "yes", "on"}
_BOOL_FALSE = {"false", "no", "off"}
_NULLS = {"", "null", "~", "none"}


def _parse_scalar(token: str) -> Any:
    """Convert a bare YAML scalar token into a Python value."""
    text = token.strip()
    if len(text) >= 2 and text[0] in "\"'" and text[-1] == text[0]:
        return text[1:-1]
    low = text.lower()
    if low in _NULLS:
        return None
    if low in _BOOL_TRUE:
        return True
    if low in _BOOL_FALSE:
        return False
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text


def _strip_comment(line: str) -> str:
    """Remove a trailing/full-line ``#`` comment that is outside quotes."""
    out = []
    quote = None
    for ch in line:
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            out.append(ch)
        elif ch == "#":
            break
        else:
            out.append(ch)
    return "".join(out)


def _split_top_level(text: str, sep: str) -> List[str]:
    """Split ``text`` on ``sep`` ignoring separators inside quotes/brackets."""
    parts: List[str] = []
    depth = 0
    quote = None
    cur = []
    for ch in text:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            cur.append(ch)
        elif ch in "[{":
            depth += 1
            cur.append(ch)
        elif ch in "]}":
            depth -= 1
            cur.append(ch)
        elif ch == sep and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return parts


def _parse_flow(text: str) -> Any:
    """Parse an inline flow value: scalar, ``[...]`` list, or ``{...}`` map."""
    text = text.strip()
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        return [_parse_flow(item) for item in _split_top_level(inner, ",")]
    if text.startswith("{") and text.endswith("}"):
        inner = text[1:-1].strip()
        result: dict = {}
        if not inner:
            return result
        for pair in _split_top_level(inner, ","):
            if ":" not in pair:
                continue
            k, v = pair.split(":", 1)
            result[_parse_scalar(k.strip())] = _parse_flow(v)
        return result
    return _parse_scalar(text)


# --------------------------------------------------------------------------
# Block parsing (indentation-aware)
# --------------------------------------------------------------------------
def _collect_lines(raw: str) -> List[Tuple[int, str]]:
    """Return (indent, content) for every significant line."""
    lines: List[Tuple[int, str]] = []
    for original in raw.splitlines():
        stripped = _strip_comment(original)
        if not stripped.strip():
            continue
        indent = len(stripped) - len(stripped.lstrip(" "))
        lines.append((indent, stripped.strip()))
    return lines


def _parse_block(lines: List[Tuple[int, str]], start: int, indent: int) -> Tuple[Any, int]:
    """Parse a block starting at ``lines[start]`` at the given indent."""
    if start >= len(lines):
        return None, start
    _, first = lines[start]
    if first.startswith("- "):
        return _parse_sequence(lines, start, indent)
    if first == "-":
        return _parse_sequence(lines, start, indent)
    return _parse_mapping(lines, start, indent)


def _parse_sequence(lines: List[Tuple[int, str]], start: int, indent: int) -> Tuple[List[Any], int]:
    items: List[Any] = []
    i = start
    while i < len(lines):
        cur_indent, content = lines[i]
        if cur_indent < indent or not (content == "-" or content.startswith("- ")):
            break
        value_text = "" if content == "-" else content[2:].strip()
        # Indentation of content sitting after the "- " marker.
        dash_indent = cur_indent + 2
        # Does this item have continuation lines deeper than the marker?
        has_continuation = (
            i + 1 < len(lines)
            and lines[i + 1][0] >= dash_indent
            and not (lines[i + 1][1] == "-" or lines[i + 1][1].startswith("- "))
        )
        if value_text and ":" in value_text and has_continuation:
            # "- key: value" followed by sibling keys -> a mapping item.
            item_lines = [(dash_indent, value_text)]
            j = i + 1
            while j < len(lines) and lines[j][0] >= dash_indent and not (
                lines[j][1] == "-" or lines[j][1].startswith("- ")
            ):
                item_lines.append(lines[j])
                j += 1
            value, _ = _parse_mapping(item_lines, 0, dash_indent)
            items.append(value)
            i = j
        elif value_text:
            items.append(_parse_flow(value_text))
            i += 1
        else:
            # Nested block belonging to this list item (first key on next line).
            value, i = _parse_block(lines, i + 1, lines[i + 1][0])
            items.append(value)
    return items, i


def _parse_mapping(lines: List[Tuple[int, str]], start: int, indent: int) -> Tuple[dict, int]:
    mapping: dict = {}
    i = start
    while i < len(lines):
        cur_indent, content = lines[i]
        if cur_indent < indent:
            break
        if cur_indent > indent:
            # Should have been consumed by a child parse; skip defensively.
            i += 1
            continue
        if content.startswith("- ") or content == "-":
            break
        key_part, _, value_part = content.partition(":")
        key = _parse_scalar(key_part.strip())
        value_text = value_part.strip()
        if value_text:
            mapping[key] = _parse_flow(value_text)
            i += 1
        else:
            # Look ahead: nested mapping or sequence at a deeper indent.
            if i + 1 < len(lines) and lines[i + 1][0] > indent:
                value, i = _parse_block(lines, i + 1, lines[i + 1][0])
                mapping[key] = value
            elif (
                i + 1 < len(lines)
                and lines[i + 1][0] == indent
                and (lines[i + 1][1] == "-" or lines[i + 1][1].startswith("- "))
            ):
                # Sequence at the same indent as its key (common YAML style).
                value, i = _parse_sequence(lines, i + 1, indent)
                mapping[key] = value
            else:
                mapping[key] = None
                i += 1
    return mapping, i


def parse_yaml(text: str) -> Any:
    """Parse a YAML document from ``text`` using the stdlib fallback parser."""
    if _pyyaml is not None:
        return _pyyaml.safe_load(text)
    lines = _collect_lines(text)
    if not lines:
        return None
    base_indent = lines[0][0]
    value, _ = _parse_block(lines, 0, base_indent)
    return value


def load_yaml(path: str) -> Any:
    """Load and parse a YAML file."""
    with open(path, "r", encoding="utf-8") as handle:
        return parse_yaml(handle.read())


def load_json(path: str) -> Any:
    """Load and parse a JSON file."""
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def load_config(path: str) -> Any:
    """Load a config file, dispatching on extension (.json vs .yaml/.yml)."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".json":
        return load_json(path)
    return load_yaml(path)


# --------------------------------------------------------------------------
# Dump helpers
# --------------------------------------------------------------------------
def _dump_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    text = str(value)
    if text == "" or any(c in text for c in ":#{}[],&*?|<>=!%@`") or text != text.strip():
        return json.dumps(text)
    return text


def dump_yaml(data: Any, indent: int = 0) -> str:
    """Serialise ``data`` to the YAML subset (round-trips the parser)."""
    if _pyyaml is not None:
        return _pyyaml.safe_dump(data, default_flow_style=False, sort_keys=False)
    pad = "  " * indent
    lines: List[str] = []
    if isinstance(data, dict):
        if not data:
            return pad + "{}\n"
        for key, value in data.items():
            if isinstance(value, (dict, list)) and value:
                lines.append(f"{pad}{key}:")
                lines.append(dump_yaml(value, indent + 1).rstrip("\n"))
            elif isinstance(value, (dict, list)):
                flow = "{}" if isinstance(value, dict) else "[]"
                lines.append(f"{pad}{key}: {flow}")
            else:
                lines.append(f"{pad}{key}: {_dump_scalar(value)}")
        return "\n".join(lines) + "\n"
    if isinstance(data, list):
        if not data:
            return pad + "[]\n"
        for item in data:
            if isinstance(item, (dict, list)) and item:
                block = dump_yaml(item, indent + 1)
                block = block.lstrip()
                lines.append(f"{pad}- {block.rstrip()}")
            else:
                lines.append(f"{pad}- {_dump_scalar(item)}")
        return "\n".join(lines) + "\n"
    return pad + _dump_scalar(data) + "\n"


def dump_json(data: Any, indent: int = 2) -> str:
    """Serialise ``data`` to JSON text."""
    return json.dumps(data, indent=indent, sort_keys=False)
