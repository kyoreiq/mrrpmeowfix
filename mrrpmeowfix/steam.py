"""Finds Steam installs, libraries, games and accounts, and starts/stops Steam."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from . import vdf

STEAM_ID64_BASE = 76561197960265728

# Runtimes, Proton builds and redistributables that show up as "apps".
TOOL_APPIDS = {
    228980, 250820, 858280, 961940, 1054830, 1070560, 1113280, 1161040, 1245040,
    1391110, 1420170, 1493710, 1580130, 1628350, 1826330, 1887720, 2180100,
    2230260, 2348590, 2805730, 3658110, 4183110,
}
TOOL_NAME = re.compile(
    r"^(Proton\b|Steam Linux Runtime|Steamworks Common|SteamVR$|Steamworks Shared)", re.I
)

FLATPAK_ID = "com.valvesoftware.Steam"


@dataclass(frozen=True)
class SteamRoot:
    path: Path
    kind: str  # native | flatpak | snap


@dataclass(frozen=True)
class Game:
    appid: int
    name: str
    installdir: Path
    library: Path
    size: int
    has_prefix: bool


@dataclass(frozen=True)
class Account:
    id64: str
    account_id: int
    name: str
    localconfig: Path


@dataclass(frozen=True)
class CompatTool:
    internal_name: str
    display: str
    kind: str  # ge | cachyos | valve | other
    installed: bool = True


def _read(path: Path) -> dict:
    try:
        return vdf.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, vdf.VDFError):
        return {}


def find_roots() -> list[SteamRoot]:
    home = Path.home()
    candidates = [
        (home / ".local/share/Steam", "native"),
        (home / ".steam/steam", "native"),
        (home / ".steam/root", "native"),
        (home / ".var/app" / FLATPAK_ID / ".local/share/Steam", "flatpak"),
        (home / ".var/app" / FLATPAK_ID / "data/Steam", "flatpak"),
        (home / "snap/steam/common/.local/share/Steam", "snap"),
    ]
    seen: set[Path] = set()
    roots = []
    for path, kind in candidates:
        try:
            real = path.resolve()
        except OSError:
            continue
        if real in seen or not (real / "steamapps").is_dir():
            continue
        seen.add(real)
        roots.append(SteamRoot(real, kind))
    return roots


def libraries(root: SteamRoot) -> list[Path]:
    data = _read(root.path / "steamapps/libraryfolders.vdf")
    folders = vdf.find(data, "libraryfolders") or {}
    libs: list[Path] = []
    for entry in folders.values():
        if isinstance(entry, dict) and entry.get("path"):
            libs.append(Path(entry["path"]))
    if not libs:
        libs.append(root.path)
    out, seen = [], set()
    for lib in libs:
        key = str(lib.resolve()) if lib.exists() else str(lib)
        if key in seen or not (lib / "steamapps").is_dir():
            continue
        seen.add(key)
        out.append(lib)
    return out


def is_tool(appid: int, name: str) -> bool:
    return appid in TOOL_APPIDS or bool(TOOL_NAME.match(name))


def games(root: SteamRoot) -> list[Game]:
    libs = libraries(root)
    prefixes = set()
    for lib in libs:
        compat = lib / "steamapps/compatdata"
        if compat.is_dir():
            prefixes.update(p.name for p in compat.iterdir())
    found: dict[int, Game] = {}
    for lib in libs:
        for acf in (lib / "steamapps").glob("appmanifest_*.acf"):
            state = vdf.find(_read(acf), "AppState")
            if not isinstance(state, dict):
                continue
            try:
                appid = int(state.get("appid", ""))
            except ValueError:
                continue
            name = state.get("name") or f"App {appid}"
            if is_tool(appid, name):
                continue
            try:
                flags = int(state.get("StateFlags", "4"))
            except ValueError:
                flags = 4
            if not flags & 4:
                continue  # still downloading for the first time
            try:
                size = int(state.get("SizeOnDisk", "0"))
            except ValueError:
                size = 0
            found[appid] = Game(
                appid=appid,
                name=name,
                installdir=lib / "steamapps/common" / state.get("installdir", ""),
                library=lib,
                size=size,
                has_prefix=str(appid) in prefixes,
            )
    return sorted(found.values(), key=lambda g: g.name.lower())


def accounts(root: SteamRoot) -> list[Account]:
    users = vdf.find(_read(root.path / "config/loginusers.vdf"), "users") or {}
    rows = []
    for id64, info in users.items():
        if not isinstance(info, dict) or not id64.isdigit():
            continue
        account_id = int(id64) - STEAM_ID64_BASE
        recent = (info.get("MostRecent") or info.get("mostrecent")) == "1"
        auto = info.get("AutoLogin") == "1"
        try:
            stamp = int(info.get("timestamp") or info.get("Timestamp") or 0)
        except ValueError:
            stamp = 0
        acc = Account(
            id64=id64,
            account_id=account_id,
            name=info.get("PersonaName") or id64,
            localconfig=root.path / "userdata" / str(account_id) / "config/localconfig.vdf",
        )
        rows.append(((recent, auto, stamp), acc))
    rows.sort(key=lambda r: r[0], reverse=True)
    return [acc for _, acc in rows]


def current_account(root: SteamRoot) -> Account | None:
    accs = accounts(root)
    return accs[0] if accs else None


def _tool_kind(name: str) -> str:
    low = name.lower()
    if low.startswith("ge-proton"):
        return "ge"
    if "cachyos" in low:
        return "cachyos"
    return "other"


def compat_tool_dirs(root: SteamRoot) -> list[Path]:
    dirs = [root.path / "compatibilitytools.d"]
    if root.kind == "native":
        dirs += [
            Path("/usr/share/steam/compatibilitytools.d"),
            Path("/usr/local/share/steam/compatibilitytools.d"),
        ]
    return dirs


def compat_tools(root: SteamRoot) -> list[CompatTool]:
    tools: dict[str, CompatTool] = {}
    for base in compat_tool_dirs(root):
        if not base.is_dir():
            continue
        for vdf_file in base.glob("*/compatibilitytool.vdf"):
            entries = vdf.find(_read(vdf_file), "compatibilitytools", "compat_tools") or {}
            for internal, info in entries.items():
                display = info.get("display_name", internal) if isinstance(info, dict) else internal
                tools[internal] = CompatTool(internal, display, _tool_kind(internal))
    experimental = any((lib / "steamapps/common/Proton - Experimental").is_dir() for lib in libraries(root))
    # Steam downloads Experimental by itself when a game is mapped to it.
    tools["proton_experimental"] = CompatTool("proton_experimental", "Proton Experimental", "valve", experimental)
    return list(tools.values())


def _ge_version(name: str) -> tuple[int, int]:
    m = re.match(r"GE-Proton(\d+)-(\d+)", name)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def newest_ge(tools: list[CompatTool]) -> CompatTool | None:
    ge = [t for t in tools if t.kind == "ge"]
    return max(ge, key=lambda t: _ge_version(t.internal_name)) if ge else None


def compat_mapping(root: SteamRoot) -> dict[str, str]:
    mapping = vdf.find(
        _read(root.path / "config/config.vdf"),
        "InstallConfigStore", "Software", "Valve", "Steam", "CompatToolMapping",
    ) or {}
    return {k: v.get("name", "") for k, v in mapping.items() if isinstance(v, dict)}


def art_path(root: SteamRoot, appid: int, kind: str = "library_600x900") -> Path | None:
    cache = root.path / "appcache/librarycache"
    for candidate in (cache / str(appid) / f"{kind}.jpg", cache / f"{appid}_{kind}.jpg"):
        if candidate.is_file():
            return candidate
    return None


def cover_path(root: SteamRoot, appid: int) -> Path | None:
    return art_path(root, appid, "library_600x900")


def _steam_command(root: SteamRoot) -> list[str]:
    if root.kind == "flatpak":
        return ["flatpak", "run", FLATPAK_ID]
    if root.kind == "snap":
        return ["snap", "run", "steam"]
    exe = shutil.which("steam")
    return [exe] if exe else [str(root.path / "steam.sh")]


def is_running() -> bool:
    me = os.getpid()
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == me:
            continue
        try:
            comm = (entry / "comm").read_text().strip()
        except OSError:
            continue
        if comm in ("steam", "steamwebhelper"):
            return True
    return False


def shutdown(root: SteamRoot, timeout: float = 30.0) -> bool:
    if not is_running():
        return True
    try:
        subprocess.run(_steam_command(root) + ["-shutdown"], timeout=15,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        pass
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_running():
            # Steam writes its config on the way out; give it a moment to finish.
            time.sleep(1.0)
            return True
        time.sleep(0.5)
    return False


def start(root: SteamRoot) -> None:
    subprocess.Popen(_steam_command(root), start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
