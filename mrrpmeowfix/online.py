"""Small cached lookups: Linux support from the Steam store and the live ProtonDB tier."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import paths

STORE = "https://store.steampowered.com/api/appdetails?appids={}&filters=platforms"
SUMMARY = "https://www.protondb.com/api/v1/reports/summaries/{}.json"
PLATFORM_AGE = 30 * 86400
TIER_AGE = 86400

_lock = threading.Lock()
_cache: dict | None = None


def _path() -> Path:
    return paths.cache_dir() / "lookups.json"


def _load() -> dict:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _cache = {}
        _cache.setdefault("platforms", {})
        _cache.setdefault("tiers", {})
    return _cache


def save() -> None:
    with _lock:
        data = json.dumps(_load())
    tmp = _path().with_suffix(".tmp")
    tmp.write_text(data, encoding="utf-8")
    tmp.replace(_path())


def _fetch_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "mrrpmeowfix"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def cached_linux(appid: int) -> bool | None:
    with _lock:
        hit = _load()["platforms"].get(str(appid))
    return None if hit is None else hit.get("linux")


def linux_native(appid: int, network: bool = True) -> bool | None:
    key = str(appid)
    with _lock:
        hit = _load()["platforms"].get(key)
    if hit and time.time() - hit.get("at", 0) < PLATFORM_AGE:
        return hit.get("linux")
    if not network:
        return hit.get("linux") if hit else None
    try:
        data = _fetch_json(STORE.format(appid)).get(key, {})
    except (OSError, ValueError, urllib.error.URLError):
        return hit.get("linux") if hit else None
    linux = bool(data.get("data", {}).get("platforms", {}).get("linux")) if data.get("success") else None
    with _lock:
        _load()["platforms"][key] = {"linux": linux, "at": int(time.time())}
    return linux


def cached_tier(appid: int) -> str | None:
    with _lock:
        hit = _load()["tiers"].get(str(appid))
    return hit.get("tier") if hit else None


def tier(appid: int, network: bool = True) -> str | None:
    key = str(appid)
    with _lock:
        hit = _load()["tiers"].get(key)
    if hit and time.time() - hit.get("at", 0) < TIER_AGE:
        return hit.get("tier")
    if not network:
        return hit.get("tier") if hit else None
    try:
        data = _fetch_json(SUMMARY.format(appid))
        value = data.get("tier")
    except urllib.error.HTTPError as e:
        value = None if e.code == 404 else (hit or {}).get("tier")
    except (OSError, ValueError, urllib.error.URLError):
        return hit.get("tier") if hit else None
    with _lock:
        _load()["tiers"][key] = {"tier": value, "at": int(time.time())}
    return value
