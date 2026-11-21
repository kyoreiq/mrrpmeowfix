"""Downloads and installs the newest GE-Proton release."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tarfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import paths, steam

RELEASES = "https://api.github.com/repos/GloriousEggroll/proton-ge-custom/releases/latest"


@dataclass
class Release:
    tag: str
    url: str
    size: int
    sha_url: str | None


def parse_release(data: dict) -> Release:
    tar = next(a for a in data.get("assets", []) if a["name"].endswith(".tar.gz"))
    sha = next((a for a in data.get("assets", []) if a["name"].endswith(".sha512sum")), None)
    return Release(data["tag_name"], tar["browser_download_url"], int(tar.get("size", 0)),
                   sha["browser_download_url"] if sha else None)


def _get(url: str, timeout: float = 30):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "mrrpmeowfix"}), timeout=timeout)


def latest() -> Release:
    with _get(RELEASES) as r:
        return parse_release(json.load(r))


def extract(tar_path: Path, dest: Path) -> str:
    dest.mkdir(parents=True, exist_ok=True)
    real_dest = dest.resolve()
    with tarfile.open(tar_path, "r:gz") as tar:
        members = tar.getmembers()
        tops = set()
        for m in members:
            target = (real_dest / m.name).resolve()
            if not str(target).startswith(str(real_dest) + os.sep) or m.isdev():
                raise ValueError(f"unsafe path in archive: {m.name}")
            if m.issym() or m.islnk():
                base = target.parent if m.issym() else real_dest
                link = (base / m.linkname).resolve()
                if not str(link).startswith(str(real_dest) + os.sep):
                    raise ValueError(f"unsafe link in archive: {m.name}")
            tops.add(m.name.split("/", 1)[0])
        if len(tops) != 1:
            raise ValueError("unexpected archive layout")
        try:
            tar.extractall(dest, members=members, filter="tar")
        except TypeError:
            tar.extractall(dest, members=members)
    return tops.pop()


def install(root: steam.SteamRoot, progress: Callable[[float, str], None] | None = None,
            release: Release | None = None) -> str:
    rel = release or latest()
    part = paths.cache_dir() / (rel.tag + ".tar.gz.part")
    digest = hashlib.sha512()
    try:
        with _get(rel.url, timeout=60) as r, open(part, "wb") as out:
            total = int(r.headers.get("Content-Length") or rel.size or 0)
            done = 0
            while True:
                block = r.read(1 << 17)
                if not block:
                    break
                out.write(block)
                digest.update(block)
                done += len(block)
                if progress and total:
                    progress(0.9 * done / total, f"Downloading {rel.tag} ({done >> 20} of {total >> 20} MB)")
        if rel.sha_url:
            with _get(rel.sha_url) as r:
                expected = r.read().decode().split()[0].strip().lower()
            if expected != digest.hexdigest():
                raise ValueError("Download was corrupted (checksum mismatch). Try again.")
        if progress:
            progress(0.92, f"Unpacking {rel.tag}")
        dest = root.path / "compatibilitytools.d"
        staging = dest / f".{rel.tag}.unpacking"
        shutil.rmtree(staging, ignore_errors=True)
        name = extract(part, staging)
        final = dest / name
        if final.exists():
            shutil.rmtree(staging, ignore_errors=True)
        else:
            (staging / name).rename(final)
            shutil.rmtree(staging, ignore_errors=True)
        if progress:
            progress(1.0, f"{rel.tag} installed")
        return name
    finally:
        part.unlink(missing_ok=True)
