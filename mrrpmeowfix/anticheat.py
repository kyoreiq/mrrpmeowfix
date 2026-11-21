"""Which games ship anti-cheat, from AreWeAntiCheatYet plus a look in the game folder."""

from __future__ import annotations

import json
import re
import time
import urllib.request
from functools import lru_cache
from pathlib import Path

from . import paths

URL = "https://raw.githubusercontent.com/AreWeAntiCheatYet/AreWeAntiCheatYet/master/games.json"
MAX_AGE = 7 * 86400


def _norm(name: str) -> str:
    name = re.sub(r"[™®©]", "", name).lower()
    return re.sub(r"\s+", " ", name).strip()


class AntiCheat:
    def __init__(self, entries: list[dict]):
        self.by_id: dict[str, list[str]] = {}
        self.by_name: dict[str, list[str]] = {}
        for e in entries:
            names = [a for a in e.get("a", []) if a]
            if not names:
                continue
            if e.get("id"):
                self.by_id[str(e["id"])] = names
            if "(" not in e.get("n", ""):
                self.by_name.setdefault(_norm(e.get("n", "")), names)

    def check(self, appid: int, name: str, installdir: Path) -> list[str]:
        found = list(self.by_id.get(str(appid)) or self.by_name.get(_norm(name)) or [])
        for label in _local(installdir):
            if label not in found:
                found.append(label)
        return found


def _local(installdir: Path) -> list[str]:
    found: list[str] = []
    try:
        entries = list(installdir.iterdir())
    except OSError:
        return found
    names = [e.name.lower() for e in entries]
    for e in entries:
        if e.is_dir():
            try:
                names += [c.name.lower() for c in e.iterdir()]
            except OSError:
                pass
    if any(n.startswith("easyanticheat") for n in names):
        found.append("Easy Anti-Cheat")
    if any(n.startswith(("battleye", "beservice")) for n in names):
        found.append("BattlEye")
    return found


def _cache() -> Path:
    return paths.cache_dir() / "anticheat.json"


@lru_cache(maxsize=1)
def load() -> AntiCheat:
    for path in (_cache(), paths.bundled("anticheat.json")):
        try:
            with open(path, encoding="utf-8") as f:
                return AntiCheat(json.load(f))
        except (OSError, ValueError):
            continue
    return AntiCheat([])


def refresh() -> bool:
    cache = _cache()
    if cache.exists() and time.time() - cache.stat().st_mtime < MAX_AGE:
        return False
    req = urllib.request.Request(URL, headers={"User-Agent": "mrrpmeowfix"})
    with urllib.request.urlopen(req, timeout=30) as r:
        games = json.load(r)
    trimmed = [
        {"n": g.get("name", ""), "s": g.get("status", ""), "a": g.get("anticheats") or [],
         "id": str((g.get("storeIds") or {}).get("steam") or "")}
        for g in games if isinstance(g, dict)
    ]
    tmp = cache.with_suffix(".tmp")
    tmp.write_text(json.dumps(trimmed, separators=(",", ":")), encoding="utf-8")
    tmp.replace(cache)
    load.cache_clear()
    return True
