"""Loads game art off the main thread: Steam's local cache first, then Steam's CDN."""

from __future__ import annotations

import threading
import urllib.request
from pathlib import Path
from typing import Callable

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, GLib  # noqa: E402

from .. import paths, steam  # noqa: E402

CDN = "https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/{name}.jpg"

_textures: dict[tuple[str, int, int], Gdk.Texture] = {}
_missing: set[str] = set()
_lock = threading.Lock()
_pool = threading.BoundedSemaphore(4)


def _cdn_file(appid: int, name: str) -> Path | None:
    folder = paths.cache_dir() / "art"
    folder.mkdir(exist_ok=True)
    target = folder / f"{appid}_{name}.jpg"
    if target.exists():
        return target if target.stat().st_size else None
    key = f"{appid}/{name}"
    if key in _missing:
        return None
    try:
        req = urllib.request.Request(CDN.format(appid=appid, name=name), headers={"User-Agent": "mrrpmeowfix"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = r.read()
    except OSError:
        _missing.add(key)
        return None
    tmp = target.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.replace(target)
    return target


def _texture(path: Path, width: int, height: int) -> Gdk.Texture | None:
    try:
        pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path), width, height, True)
    except GLib.Error:
        return None
    fmt = Gdk.MemoryFormat.R8G8B8A8 if pb.get_has_alpha() else Gdk.MemoryFormat.R8G8B8
    return Gdk.MemoryTexture.new(pb.get_width(), pb.get_height(), fmt, pb.read_pixel_bytes(), pb.get_rowstride())


def load(root: steam.SteamRoot | None, appid: int, kinds: list[str], width: int, height: int,
         callback: Callable[[Gdk.Texture | None], None]) -> None:
    """kinds are Steam art names in order of preference, e.g. ["library_600x900", "header"]."""
    key = (f"{appid}:{','.join(kinds)}", width, height)
    with _lock:
        hit = _textures.get(key)
    if hit is not None:
        callback(hit)
        return

    def work():
        with _pool:
            tex = None
            for kind in kinds:
                path = steam.art_path(root, appid, kind) if root else None
                path = path or _cdn_file(appid, kind)
                if path:
                    tex = _texture(path, width, height)
                    if tex:
                        break
            if tex is not None:
                with _lock:
                    _textures[key] = tex
            GLib.idle_add(lambda: callback(tex) and False)

    threading.Thread(target=work, daemon=True).start()
