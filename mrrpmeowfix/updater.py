"""Keeps the installed app up to date from the GitHub releases of the repo in data/source.json."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import sys
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import VERSION, fixlist, paths

API = "https://api.github.com/repos/{repo}/releases/latest"
CHECK_EVERY = 6 * 3600
ZIP_ROOT = "mrrpmeowfix/"
KEEP = ("mrrpmeowfix/", "data/")


@dataclass
class Release:
    version: str
    zip_url: str
    sha_url: str
    notes: str


def parse_version(text: str) -> tuple[int, ...]:
    m = re.fullmatch(r"v?(\d+(?:\.\d+)*)", (text or "").strip())
    return tuple(int(p) for p in m.group(1).split(".")) if m else ()


def newer(candidate: str, current: str) -> bool:
    a, b = parse_version(candidate), parse_version(current)
    return bool(a) and a > b


def parse_release(data: dict) -> Release | None:
    version = (data.get("tag_name") or "").lstrip("v")
    if not parse_version(version):
        return None
    assets = {a.get("name"): a.get("browser_download_url") for a in data.get("assets", []) if isinstance(a, dict)}
    zip_url = assets.get(f"mrrpmeowfix-{version}.zip")
    sha_url = assets.get(f"mrrpmeowfix-{version}.zip.sha256")
    if not zip_url or not sha_url:
        return None
    return Release(version, zip_url, sha_url, (data.get("body") or "").strip())


def installed_dir() -> Path:
    return paths.data_dir() / "app"


def is_installed_copy() -> bool:
    try:
        return paths.APP_ROOT.resolve() == installed_dir().resolve()
    except OSError:
        return False


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "mrrpmeowfix"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read(100_000_000)


def latest(src: dict | None = None, fetch: Callable[[str], bytes] = _fetch) -> Release | None:
    src = src or fixlist.source()
    if not fixlist.REPO_RE.match(src.get("repo") or ""):
        return None
    data = json.loads(fetch(API.format(repo=src["repo"])))
    return parse_release(data) if isinstance(data, dict) else None


def _extract(payload: bytes, staging: Path) -> None:
    real = staging.resolve()
    with zipfile.ZipFile(io.BytesIO(payload)) as z:
        for info in z.infolist():
            name = info.filename
            if not name.startswith(ZIP_ROOT):
                raise ValueError(f"unexpected file in update: {name}")
            rel = name[len(ZIP_ROOT):]
            if not rel.startswith(KEEP) or info.is_dir():
                continue
            target = (real / rel).resolve()
            if not str(target).startswith(str(real) + os.sep):
                raise ValueError(f"unsafe path in update: {name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)


def install(rel: Release, app_dir: Path | None = None, cache: Path | None = None,
            fetch: Callable[[str], bytes] = _fetch, progress: Callable[[str], None] | None = None) -> str:
    app_dir = app_dir or installed_dir()
    if progress:
        progress(f"Downloading mrrpmeowfix {rel.version}")
    payload = fetch(rel.zip_url)
    expected = fetch(rel.sha_url).decode(errors="replace").split()
    if not expected or expected[0].lower() != hashlib.sha256(payload).hexdigest():
        raise ValueError("The update download didn't match its checksum, so it wasn't installed.")

    staging = app_dir.parent / "app.new"
    old = app_dir.parent / "app.old"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        _extract(payload, staging)
        init = staging / "mrrpmeowfix/__init__.py"
        if not init.exists() or f'VERSION = "{rel.version}"' not in init.read_text(encoding="utf-8"):
            raise ValueError("The update didn't contain the version it said it would.")
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    shutil.rmtree(old, ignore_errors=True)
    app_dir.rename(old)
    try:
        staging.rename(app_dir)
    except OSError:
        old.rename(app_dir)
        raise
    return rel.version


def cleanup_old(app_dir: Path | None = None) -> None:
    shutil.rmtree((app_dir or installed_dir()).parent / "app.old", ignore_errors=True)


def refresh_desktop_files() -> None:
    """After an update, copy the icon, fonts and menu entry from the new version."""
    home_data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    launcher = Path.home() / ".local/bin/mrrpmeowfix"
    icon_dir = home_data / "icons/hicolor/scalable/apps"
    font_dir = home_data / "fonts/mrrpmeowfix"
    apps_dir = home_data / "applications"
    for d in (icon_dir, font_dir, apps_dir):
        d.mkdir(parents=True, exist_ok=True)
    shutil.copy2(paths.bundled("icons", f"{paths.APP_ID}.svg"), icon_dir)
    for font in paths.bundled("fonts").glob("*.ttf"):
        shutil.copy2(font, font_dir)
    entry = paths.bundled(f"{paths.APP_ID}.desktop").read_text(encoding="utf-8")
    (apps_dir / f"{paths.APP_ID}.desktop").write_text(entry.replace("@EXEC@", str(launcher)), encoding="utf-8")


def restart() -> None:
    os.execv(sys.executable, [sys.executable, "-m", "mrrpmeowfix"])


__all__ = ["Release", "VERSION", "cleanup_old", "install", "is_installed_copy", "latest", "newer",
           "parse_release", "refresh_desktop_files", "restart"]
