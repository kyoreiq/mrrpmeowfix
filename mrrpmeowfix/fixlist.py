"""The fix list: per-game fixes the owner publishes in the GitHub repo, picked up by every copy."""

from __future__ import annotations

import json
import re
import time
import urllib.request
from functools import lru_cache
from pathlib import Path

from . import paths

MAX_AGE = 6 * 3600
PROTON_CHOICES = {"ge", "experimental", "default"}
REPO_RE = re.compile(r"^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$")


def source() -> dict:
    try:
        with open(paths.bundled("source.json"), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    return {"repo": str(data.get("repo") or ""), "branch": str(data.get("branch") or "main")}


def raw_url(src: dict) -> str | None:
    repo = src.get("repo") or ""
    if not REPO_RE.match(repo) or ".." in repo:
        return None
    return f"https://raw.githubusercontent.com/{repo}/{src.get('branch') or 'main'}/fixes/community.json"


def _strings(value) -> list[str]:
    return [v for v in value if isinstance(v, str)][:40] if isinstance(value, list) else []


def clean(raw: dict) -> dict[str, dict]:
    games = {}
    for appid, entry in (raw.get("games") or {}).items():
        if not str(appid).isdigit() or not isinstance(entry, dict):
            continue
        proton = entry.get("proton")
        note = entry.get("note")
        games[str(appid)] = {
            "add": _strings(entry.get("add")),
            "block": _strings(entry.get("block")),
            "proton": proton if proton in PROTON_CHOICES else None,
            "note": note[:300] if isinstance(note, str) and note.strip() else None,
        }
    return games


class FixList:
    def __init__(self, games: dict[str, dict] | None = None, updated: str = ""):
        self.games = games or {}
        self.updated = updated

    def get(self, appid: int) -> dict | None:
        return self.games.get(str(appid))

    def __len__(self) -> int:
        return len(self.games)


def _cache() -> Path:
    return paths.cache_dir() / "community.json"


@lru_cache(maxsize=1)
def load() -> FixList:
    for path in (_cache(), paths.bundled("community.json")):
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(raw, dict):
            return FixList(clean(raw), str(raw.get("updated") or ""))
    return FixList()


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "mrrpmeowfix", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read(2_000_000)


def refresh(src: dict | None = None, force: bool = False) -> bool:
    """Fetch the list if it's older than MAX_AGE. Returns True when the list changed."""
    url = raw_url(src or source())
    if url is None:
        return False
    cache = _cache()
    if not force and cache.exists() and time.time() - cache.stat().st_mtime < MAX_AGE:
        return False
    data = _fetch(url)
    raw = json.loads(data)
    if not isinstance(raw, dict):
        raise ValueError("the fix list isn't a JSON object")
    old = cache.read_bytes() if cache.exists() else b""
    tmp = cache.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(cache)
    load.cache_clear()
    return data != old
