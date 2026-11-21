"""Parsing and merging of Steam launch options.

Two rules matter here. Tokens taken from report data are only accepted in a
few plain shapes, so nothing from the internet can turn into a shell command.
And the user's own text is never rewritten: we only insert words at the
front, after their leading VAR=value words, or at the end, and remove words
we inserted ourselves.
"""

from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass, field

COMMAND = "%command%"

WRAPPERS = {"gamemoderun", "mangohud", "game-performance", "prime-run"}

_ENV = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=([A-Za-z0-9_.,:+=-]*)$")
_ENV_PREFIX = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_FLAG = re.compile(r"^[-+][A-Za-z0-9_][A-Za-z0-9_.:=,-]*$")
_VALUE = re.compile(r"^[A-Za-z0-9_.:,=][A-Za-z0-9_.:,=-]*$")
_OPERATORS = set(";&|<>()`")

UNPARSEABLE = "Launch options couldn't be read (unbalanced quotes), so they were left alone."
SHELL = "Launch options use shell commands, so they were left alone."
CUSTOM = "The game starts through your own command, so game arguments weren't added."
ALREADY = "You already set {key} yourself."


@dataclass(frozen=True)
class Token:
    kind: str  # env | wrapper | arg
    text: str
    key: str


@dataclass
class MergeResult:
    text: str
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    inserted_command: bool = False


def sanitize(text: str) -> Token | None:
    text = text.strip()
    if not text:
        return None
    m = _ENV.match(text)
    if m:
        return Token("env", text, m.group(1))
    if text in WRAPPERS:
        return Token("wrapper", text, text)
    parts = text.split(" ")
    if len(parts) == 1 and _FLAG.match(parts[0]):
        return Token("arg", text, parts[0])
    if len(parts) == 2 and _FLAG.match(parts[0]) and _VALUE.match(parts[1]):
        return Token("arg", text, parts[0])
    return None


def split_report(text: str) -> list[Token]:
    """Split one report's launch options into safe tokens, or [] if it's anything unusual."""
    try:
        words = shlex.split(text)
    except ValueError:
        return []
    if COMMAND in words:
        i = words.index(COMMAND)
        before, after = words[:i], words[i + 1:]
    else:
        lead = 0
        while lead < len(words) and (_ENV.match(words[lead]) or words[lead] in WRAPPERS):
            lead += 1
        before, after = words[:lead], words[lead:]

    tokens: list[Token] = []
    for word in before:
        tok = sanitize(word)
        if tok is None or tok.kind == "arg":
            return []
        tokens.append(tok)

    args: list[str] = []
    for word in after:
        if word[:1] in "-+":
            args.append(word)
        elif args and " " not in args[-1]:
            args[-1] += " " + word
    for arg in args:
        tok = sanitize(arg)
        if tok is not None and tok.kind == "arg":
            tokens.append(tok)
    return tokens


class _Unbalanced(ValueError):
    pass


@dataclass
class _Seg:
    ws: str
    raw: str
    has_op: bool = False


def _segments(s: str) -> tuple[list[_Seg], str]:
    segs: list[_Seg] = []
    i, n = 0, len(s)
    ws_start = 0
    while i < n:
        if s[i].isspace():
            i += 1
            continue
        ws = s[ws_start:i]
        start, has_op = i, False
        while i < n and not s[i].isspace():
            c = s[i]
            if c == "\\":
                i += 2
                continue
            if c in "\"'":
                quote = c
                i += 1
                while i < n and s[i] != quote:
                    i += 2 if (quote == '"' and s[i] == "\\") else 1
                if i >= n:
                    raise _Unbalanced(s)
                i += 1
                continue
            if c in _OPERATORS or (c == "$" and i + 1 < n and s[i + 1] == "("):
                has_op = True
            i += 1
        segs.append(_Seg(ws, s[start:i], has_op))
        ws_start = i
    return segs, s[ws_start:]


def _render(segs: list[_Seg], tail: str) -> str:
    return "".join(seg.ws + seg.raw for seg in segs) + tail


def _insert(segs: list[_Seg], index: int, raw: str) -> None:
    if index == 0 and segs:
        segs.insert(0, _Seg(segs[0].ws, raw))
        segs[1].ws = " "
    else:
        segs.insert(index, _Seg(" " if segs else "", raw))


def _delete(segs: list[_Seg], index: int) -> None:
    gone = segs.pop(index)
    if index == 0 and segs:
        segs[0].ws = gone.ws


def _find_run(segs: list[_Seg], words: list[str]) -> int:
    raws = [seg.raw for seg in segs]
    for i in range(len(raws) - len(words) + 1):
        if raws[i:i + len(words)] == words:
            return i
    return -1


def _is_env_word(raw: str) -> bool:
    return bool(_ENV_PREFIX.match(raw))


def merge(current: str, add: list[Token], remove: list[str]) -> MergeResult:
    result = MergeResult(text=current)
    try:
        segs, tail = _segments(current)
    except _Unbalanced:
        result.skipped = [(t.text, UNPARSEABLE) for t in add]
        return result
    if any(seg.has_op for seg in segs):
        result.skipped = [(t.text, SHELL) for t in add]
        return result

    for text in remove:
        if text == COMMAND:
            continue
        words = text.split(" ")
        at = _find_run(segs, words)
        if at >= 0:
            for _ in words:
                _delete(segs, at)
            result.removed.append(text)
    if COMMAND in remove and segs and segs[0].raw == COMMAND:
        _delete(segs, 0)
        result.removed.append(COMMAND)

    raws = [seg.raw for seg in segs]
    has_cmd = COMMAND in raws
    embedded = not has_cmd and any(COMMAND in raw for raw in raws)
    args_only = not has_cmd and not embedded

    env_present: dict[str, str] = {}
    for raw in raws:
        if _is_env_word(raw):
            env_present.setdefault(raw.split("=", 1)[0], raw)
    wrappers_present = {os.path.basename(raw) for raw in raws if "'" not in raw and '"' not in raw}
    flags_present = {raw for raw in raws if raw[:1] in "-+"}

    new_env: list[Token] = []
    new_wrap: list[Token] = []
    new_args: list[Token] = []
    for tok in add:
        if tok.kind == "env":
            if tok.key in env_present:
                if env_present[tok.key] != tok.text:
                    result.skipped.append((tok.text, ALREADY.format(key=tok.key)))
                continue
            env_present[tok.key] = tok.text
            new_env.append(tok)
        elif tok.kind == "wrapper":
            if tok.key in wrappers_present:
                continue
            wrappers_present.add(tok.key)
            new_wrap.append(tok)
        else:
            if tok.key in flags_present:
                continue
            if embedded:
                result.skipped.append((tok.text, CUSTOM))
                continue
            flags_present.add(tok.key)
            new_args.append(tok)

    if args_only and (new_env or new_wrap or (not segs and new_args)):
        _insert(segs, 0, COMMAND)
        result.inserted_command = True
        lead = 0
    else:
        lead = 0
        while lead < len(segs) and _is_env_word(segs[lead].raw):
            lead += 1

    for i, tok in enumerate(new_env):
        _insert(segs, i, tok.text)
    pos = len(new_env) + lead
    for i, tok in enumerate(new_wrap):
        _insert(segs, pos + i, tok.text)
    for tok in new_args:
        _insert(segs, len(segs), tok.text)

    result.added = [t.text for t in new_env + new_wrap + new_args]
    result.text = _render(segs, tail)
    return result
