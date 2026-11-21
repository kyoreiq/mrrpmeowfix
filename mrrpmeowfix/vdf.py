"""Reader and writer for Steam's text KeyValues (.vdf / .acf) files."""

from __future__ import annotations

from typing import Any

_ESCAPES = {"n": "\n", "t": "\t", "\\": "\\", '"': '"'}


class VDFError(ValueError):
    pass


def _tokens(text: str):
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
        elif c == "/" and text.startswith("//", i):
            nl = text.find("\n", i)
            i = n if nl == -1 else nl + 1
        elif c in "{}":
            yield c, None
            i += 1
        elif c == "[":
            # Platform conditionals like [$WIN32]; Steam's own Linux files don't need them.
            end = text.find("]", i)
            if end == -1:
                raise VDFError("unterminated conditional")
            i = end + 1
        elif c == '"':
            i += 1
            out = []
            while True:
                if i >= n:
                    raise VDFError("unterminated string")
                c = text[i]
                if c == "\\" and i + 1 < n and text[i + 1] in _ESCAPES:
                    out.append(_ESCAPES[text[i + 1]])
                    i += 2
                elif c == '"':
                    i += 1
                    break
                else:
                    out.append(c)
                    i += 1
            yield "s", "".join(out)
        else:
            start = i
            while i < n and text[i] not in ' \t\r\n{}"':
                i += 1
            yield "s", text[start:i]


def loads(text: str) -> dict[str, Any]:
    if text.startswith("﻿"):
        text = text[1:]
    root: dict[str, Any] = {}
    stack = [root]
    key: str | None = None
    for kind, value in _tokens(text):
        current = stack[-1]
        if kind == "s":
            if key is None:
                key = value
            else:
                current[key] = value
                key = None
        elif kind == "{":
            if key is None:
                raise VDFError("block without a key")
            existing = current.get(key)
            block = existing if isinstance(existing, dict) else {}
            current[key] = block
            stack.append(block)
            key = None
        else:
            if len(stack) == 1:
                raise VDFError("unexpected }")
            stack.pop()
    if len(stack) != 1 or key is not None:
        raise VDFError("unexpected end of file")
    return root


def _quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def dumps(d: dict[str, Any]) -> str:
    lines: list[str] = []

    def walk(block: dict[str, Any], depth: int) -> None:
        pad = "\t" * depth
        for k, v in block.items():
            if isinstance(v, dict):
                lines.append(pad + _quote(k))
                lines.append(pad + "{")
                walk(v, depth + 1)
                lines.append(pad + "}")
            else:
                lines.append(pad + _quote(k) + "\t\t" + _quote(str(v)))

    walk(d, 0)
    return "\n".join(lines) + "\n"


def _child(block: Any, key: str) -> str | None:
    if not isinstance(block, dict):
        return None
    if key in block:
        return key
    low = key.lower()
    for k in block:
        if k.lower() == low:
            return k
    return None


def find(d: dict[str, Any], *keys: str) -> Any:
    node: Any = d
    for key in keys:
        real = _child(node, key)
        if real is None:
            return None
        node = node[real]
    return node


def ensure(d: dict[str, Any], *keys: str) -> dict[str, Any]:
    node = d
    for key in keys:
        real = _child(node, key)
        if real is None or not isinstance(node[real], dict):
            real = real or key
            node[real] = {}
        node = node[real]
    return node
