"""What each launch option does and how careful we need to be with it."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache

from . import paths
from .launchopts import Token

NORMAL, RISKY, NEVER = "normal", "risky", "never"


@dataclass(frozen=True)
class Entry:
    level: str
    label: str
    about: str
    known: bool = True


class Knowledge:
    def __init__(self, table: dict):
        self.wrappers = table.get("wrappers", {})
        self.env = table.get("env", {})
        self.args = table.get("args", {})

    def describe(self, tok: Token) -> Entry:
        table = {"env": self.env, "wrapper": self.wrappers, "arg": self.args}[tok.kind]
        info = table.get(tok.key)
        if info is None:
            if tok.kind == "env":
                return Entry(RISKY, f"Set {tok.key}", "A setting other players used for this game.", False)
            return Entry(NORMAL, f"Launch argument {tok.text}", "An argument other players used for this game.", False)
        level = info.get("level", RISKY)
        return Entry(level, info.get("label", tok.text), info.get("about", ""), True)

    def classify(self, tok: Token, gpu: str, anticheat: bool, hybrid: bool) -> Entry:
        entry = self.describe(tok)
        info = {"env": self.env, "wrapper": self.wrappers, "arg": self.args}[tok.kind].get(tok.key, {})
        level = entry.level
        if level == "hybrid":
            level = NORMAL if hybrid else NEVER
        wanted_gpu = info.get("gpu")
        if wanted_gpu and wanted_gpu != gpu:
            level = NEVER
        if anticheat and level == NORMAL and not info.get("ac_safe"):
            level = RISKY
        return Entry(level, entry.label, entry.about, entry.known)


@lru_cache(maxsize=1)
def load() -> Knowledge:
    with open(paths.bundled("fixes.json"), encoding="utf-8") as f:
        return Knowledge(json.load(f))
