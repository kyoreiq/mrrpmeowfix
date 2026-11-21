"""Builds and reads the fix index from ProtonDB's public monthly report dump.

The dump is one big JSON array (hundreds of MB), so it is read one object at
a time and boiled down to per-game counts split by GPU brand.
"""

from __future__ import annotations

import gzip
import io
import json
import os
import re
import tarfile
import time
import urllib.request
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Iterator, TextIO

from . import paths
from .launchopts import split_report

DUMP_LISTING = "https://api.github.com/repos/bdefore/protondb-data/contents/reports"
USER_AGENT = "mrrpmeowfix"

WINDOW = 730 * 86400
MIN_REPORTS = 5
MIN_GOOD = 5
BUCKETS = ("nvidia", "amd", "intel")

FAULT_KEYS = (
    "audioFaults", "graphicalFaults", "inputFaults", "performanceFaults",
    "saveGameFaults", "significantBugs", "stabilityFaults", "windowingFaults",
)

VERB_RE = re.compile(
    r"\b(vcrun20(?:05|08|10|12|13|15|17|19|22)|vcrun6|d3dx9(?:_\d\d)?|d3dx1[01](?:_\d\d)?|"
    r"d3dcompiler_4[37]|dotnet(?:desktop)?\d{1,3}|xact(?:_x64)?|xinput|corefonts|mfc42|quartz|"
    r"wmp(?:9|10|11)|physx|xna40|msxml[36]|gdiplus|devenum|lavfilters|faudio)\b"
)

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
DUMP_NAME = re.compile(r"^reports_([a-z]{3})(\d+)_(\d{4})\.tar\.gz$")


def iter_reports(f: TextIO, chunk: int = 1 << 20) -> Iterator[dict]:
    decoder = json.JSONDecoder()
    buf, pos, eof, started = "", 0, False, False

    def fill() -> None:
        nonlocal buf, pos, eof
        more = f.read(chunk)
        if more:
            buf, pos = buf[pos:] + more, 0
        else:
            eof = True

    while True:
        while True:
            while pos < len(buf) and buf[pos] in " \t\r\n,":
                pos += 1
            if pos < len(buf) or eof:
                break
            fill()
        if pos >= len(buf):
            raise ValueError("report file ended early")
        if not started:
            if buf[pos] != "[":
                raise ValueError("report file is not a JSON array")
            pos += 1
            started = True
            continue
        if buf[pos] == "]":
            return
        try:
            obj, end = decoder.raw_decode(buf, pos)
        except json.JSONDecodeError:
            if eof:
                raise
            fill()
            continue
        pos = end
        yield obj


def gpu_vendor(text: str) -> str:
    low = text.lower()
    if any(s in low for s in ("nvidia", "geforce", "quadro", "rtx ", "gtx ")):
        return "nvidia"
    if any(s in low for s in ("amd", "radeon", "ati ", "vangogh", "navi", "vega")):
        return "amd"
    if any(s in low for s in ("intel", "iris", "arc a", "uhd graphics")):
        return "intel"
    return "other"


def _notes_text(resp: dict) -> str:
    parts = []
    notes = resp.get("notes")
    if isinstance(notes, dict):
        parts.extend(v for v in notes.values() if isinstance(v, str))
    elif isinstance(notes, str):
        parts.append(notes)
    if isinstance(resp.get("concludingNotes"), str):
        parts.append(resp["concludingNotes"])
    return " ".join(parts).lower()


def _verbs(resp: dict) -> set[str]:
    text = _notes_text(resp)
    if "protontricks" not in text and "winetricks" not in text:
        return set()
    return set(VERB_RE.findall(text))


def _new_bucket() -> dict:
    return {"n": 0, "g": 0, "f": 0, "v": Counter(), "ge": Counter(), "lo": Counter(), "vb": Counter()}


def distill(reports: Iterable[dict], now: float | None = None, min_count: int = 1) -> dict:
    now = time.time() if now is None else now
    cutoff = now - WINDOW
    games: dict[str, dict] = {}
    for rep in reports:
        app = rep.get("app") or {}
        appid = str((app.get("steam") or {}).get("appId") or "")
        if not appid.isdigit():
            continue
        resp = rep.get("responses") or {}
        game = games.setdefault(appid, {"t": "", "recent": {}, "all": {}})
        if app.get("title"):
            game["t"] = app["title"]

        info = rep.get("systemInfo") or {}
        vendor = gpu_vendor(str(info.get("gpu", "")))
        if vendor == "other":
            vendor = gpu_vendor(str(info.get("gpuDriver", "")))
        good = resp.get("verdict") == "yes"
        faultless = good and all(resp.get(k) in (None, "no") for k in FAULT_KEYS)
        variant = resp.get("variant") or "unknown"
        ge = resp.get("customProtonVersion") or ""
        tokens = {t.text for t in split_report(str(resp.get("launchOptions") or ""))} if good else set()
        verbs = _verbs(resp) if good else set()

        stores = [game["all"]]
        if rep.get("timestamp", 0) >= cutoff:
            stores.append(game["recent"])
        names = ("all",) if vendor == "other" else (vendor, "all")
        for store in stores:
            for name in names:
                c = store.get(name)
                if c is None:
                    c = store[name] = _new_bucket()
                c["n"] += 1
                if not good:
                    continue
                c["g"] += 1
                c["f"] += faultless
                c["v"][variant] += 1
                if ge.startswith("GE-Proton"):
                    c["ge"][ge] += 1
                c["lo"].update(tokens)
                c["vb"].update(verbs)

    out: dict[str, dict] = {}
    for appid, game in games.items():
        buckets = {}
        for name, every in game["all"].items():
            recent = game["recent"].get(name)
            use, window = (recent, "recent") if recent and recent["n"] >= MIN_REPORTS else (every, "all")
            buckets[name] = {
                "n": use["n"], "g": use["g"], "f": use["f"], "w": window,
                "v": dict(use["v"]),
                "ge": dict(use["ge"].most_common(3)),
                "lo": {k: v for k, v in use["lo"].items() if v >= min_count},
                "vb": {k: v for k, v in use["vb"].items() if v >= min_count},
            }
        out[appid] = {"t": game["t"], "b": buckets}
    return {"version": 1, "built": int(now), "source": "", "games": out}


def save(data: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"))
    os.replace(tmp, path)


@dataclass
class GameStats:
    appid: int
    title: str
    buckets: dict

    def bucket(self, gpu: str) -> tuple[str, dict]:
        own = self.buckets.get(gpu)
        if own and own["g"] >= MIN_GOOD:
            return gpu, own
        return "all", self.buckets.get("all") or {"n": 0, "g": 0, "f": 0, "v": {}, "ge": {}, "lo": {}, "vb": {}}

    @property
    def total(self) -> int:
        return (self.buckets.get("all") or {}).get("n", 0)

    def rough_tier(self) -> str | None:
        b = self.buckets.get("all")
        if not b or not b["n"]:
            return None
        good, clean = b["g"] / b["n"], b["f"] / b["n"]
        if good >= 0.9 and clean >= 0.6:
            return "platinum"
        if good >= 0.8:
            return "gold"
        if good >= 0.6:
            return "silver"
        if good >= 0.4:
            return "bronze"
        return "borked"


class Index:
    def __init__(self, data: dict | None = None):
        data = data or {"games": {}}
        self.games: dict[str, dict] = data.get("games", {})
        self.built: int = data.get("built", 0)
        self.source: str = data.get("source", "")
        self._titles: list[tuple[str, str]] | None = None

    @classmethod
    def from_file(cls, path: Path) -> "Index":
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return cls(json.load(f))

    def get(self, appid: int) -> GameStats | None:
        g = self.games.get(str(appid))
        return GameStats(int(appid), g["t"], g["b"]) if g else None

    def search(self, text: str, limit: int = 50) -> list[GameStats]:
        text = text.strip().lower()
        if not text:
            return []
        if self._titles is None:
            self._titles = [(g["t"].lower(), appid) for appid, g in self.games.items() if g.get("t")]
        if text.isdigit() and text in self.games:
            return [self.get(int(text))]
        hits = []
        for title, appid in self._titles:
            at = title.find(text)
            if at >= 0:
                stats = self.get(int(appid))
                hits.append((at != 0, -stats.total, title, stats))
        hits.sort(key=lambda h: h[:3])
        return [h[3] for h in hits[:limit]]

    def describe_source(self) -> str:
        m = DUMP_NAME.match(self.source + ".tar.gz") if self.source else None
        if not m:
            return "bundled data"
        return f"{m.group(1).capitalize()} {m.group(3)}"


def cache_file() -> Path:
    return paths.cache_dir() / "index.json.gz"


def load() -> Index:
    best = Index()
    for path in (cache_file(), paths.bundled("index.json.gz")):
        try:
            idx = Index.from_file(path)
        except (OSError, ValueError, EOFError):
            continue
        if idx.built > best.built:
            best = idx
    return best


def newest_dump(names: Iterable[str]) -> str | None:
    best, key = None, None
    for name in names:
        m = DUMP_NAME.match(name)
        if not m or m.group(1) not in MONTHS:
            continue
        k = (int(m.group(3)), MONTHS[m.group(1)], int(m.group(2)))
        if key is None or k > key:
            best, key = name, k
    return best


def _get(url: str, timeout: float = 30):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(req, timeout=timeout)


def latest_dump() -> tuple[str, str] | None:
    with _get(DUMP_LISTING) as r:
        listing = json.load(r)
    urls = {e["name"]: e.get("download_url") for e in listing if isinstance(e, dict)}
    name = newest_dump(urls)
    return (name, urls[name]) if name and urls.get(name) else None


def build_from_tarball(tar_path: Path, source: str, progress: Callable[[float, str], None] | None = None,
                       min_count: int = 3) -> dict:
    with tarfile.open(tar_path, "r:gz") as tar:
        member = next((m for m in tar.getmembers() if m.name.endswith(".json")), None)
        if member is None:
            raise ValueError("no report file in the download")
        raw = tar.extractfile(member)
        if raw is None:
            raise ValueError("no report file in the download")
        counted = 0

        def reports():
            nonlocal counted
            for rep in iter_reports(io.TextIOWrapper(raw, encoding="utf-8")):
                counted += 1
                if progress and counted % 20000 == 0:
                    progress(0.5 + min(0.45, counted / 900000), f"Reading reports ({counted:,})")
                yield rep

        data = distill(reports(), min_count=min_count)
    data["source"] = source
    return data


def refresh(progress: Callable[[float, str], None] | None = None, current_source: str = "") -> bool:
    """Download the newest dump if it's newer than what we have. Returns True if the index changed."""
    found = latest_dump()
    if not found:
        return False
    name, url = found
    source = name.removesuffix(".tar.gz")
    if source == current_source:
        return False
    part = paths.cache_dir() / (name + ".part")
    try:
        with _get(url, timeout=60) as r, open(part, "wb") as out:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while True:
                block = r.read(1 << 16)
                if not block:
                    break
                out.write(block)
                done += len(block)
                if progress and total:
                    progress(0.5 * done / total, f"Downloading reports ({done >> 20} of {total >> 20} MB)")
        data = build_from_tarball(part, source, progress)
        save(data, cache_file())
        if progress:
            progress(1.0, "Fix data updated")
        return True
    finally:
        part.unlink(missing_ok=True)
