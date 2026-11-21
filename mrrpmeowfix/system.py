"""Looks at the PC and says what's missing, with the command to fix it for this distro."""

from __future__ import annotations

import grp
import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import steam

VENDORS = {"0x10de": "nvidia", "0x1002": "amd", "0x8086": "intel"}
GPU_NAMES = {"nvidia": "NVIDIA", "amd": "AMD", "intel": "Intel", "unknown": "Unknown GPU"}

# package key -> manager -> packages (or a full command when it starts with "!")
PACKAGES: dict[str, dict[str, str]] = {
    "gamemode": {"pacman": "gamemode lib32-gamemode", "apt": "gamemode", "dnf": "gamemode gamemode.i686",
                 "zypper": "gamemode libgamemode0-32bit libgamemodeauto0-32bit"},
    "mangohud": {"pacman": "mangohud lib32-mangohud", "apt": "mangohud", "dnf": "mangohud mangohud.i686",
                 "zypper": "mangohud mangohud-32bit"},
    "protontricks": {"pacman": "protontricks", "apt": "protontricks", "dnf": "protontricks", "zypper": "protontricks",
                     None: "!flatpak install flathub com.github.Matoking.protontricks"},
    "vulkan32-nvidia": {"pacman": "lib32-nvidia-utils",
                        "apt": "!sudo dpkg --add-architecture i386 && sudo apt update && "
                               "sudo apt install libnvidia-gl-$(cat /sys/module/nvidia/version | cut -d. -f1):i386",
                        "dnf": "xorg-x11-drv-nvidia-libs.i686", "zypper": "nvidia-gl-G06-32bit"},
    "vulkan32-amd": {"pacman": "lib32-vulkan-radeon",
                     "apt": "!sudo dpkg --add-architecture i386 && sudo apt update && sudo apt install mesa-vulkan-drivers:i386",
                     "dnf": "mesa-vulkan-drivers.i686", "zypper": "libvulkan_radeon-32bit"},
    "vulkan32-intel": {"pacman": "lib32-vulkan-intel",
                       "apt": "!sudo dpkg --add-architecture i386 && sudo apt update && sudo apt install mesa-vulkan-drivers:i386",
                       "dnf": "mesa-vulkan-drivers.i686", "zypper": "libvulkan_intel-32bit"},
}
INSTALL = {"pacman": "sudo pacman -S --needed", "apt": "sudo apt install", "dnf": "sudo dnf install",
           "zypper": "sudo zypper install"}

LIB32_DIRS = [Path("/usr/lib32"), Path("/usr/lib/i386-linux-gnu"), Path("/usr/lib")]
MAP_COUNT_WANTED = 1048576
MAP_COUNT_FIX = ("echo 'vm.max_map_count = 2147483642' | sudo tee /etc/sysctl.d/80-gamecompatibility.conf"
                 " && sudo sysctl --system")

TERMINALS = [
    ("kitty", []), ("alacritty", ["-e"]), ("foot", []), ("ghostty", ["-e"]), ("wezterm", ["start", "--"]),
    ("konsole", ["-e"]), ("gnome-terminal", ["--"]), ("kgx", ["-e"]), ("ptyxis", ["--"]),
    ("xfce4-terminal", ["-x"]), ("tilix", ["-e"]), ("xterm", ["-e"]),
]


@dataclass
class SystemInfo:
    distro: str = "Linux"
    os_release: dict = field(default_factory=dict)
    pkg: str | None = None
    gpu: str = "unknown"
    gpu_name: str = ""
    driver: str = ""
    hybrid: bool = False
    laptop: bool = False
    session: str = ""
    desktop: str = ""
    cpu: str = ""
    ram_gb: int = 0
    kernel: str = ""


@dataclass
class Check:
    id: str
    title: str
    ok: bool | None  # None means just information
    detail: str
    command: str | None = None
    action: str | None = None


def parse_os_release(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        if "=" not in line or line.startswith("#"):
            continue
        k, v = line.split("=", 1)
        try:
            v = shlex.split(v)[0] if v else ""
        except (ValueError, IndexError):
            pass
        out[k.strip()] = v
    return out


def package_manager(osr: dict, which: Callable[[str], str | None] = shutil.which) -> str | None:
    ids = (osr.get("ID", "") + " " + osr.get("ID_LIKE", "")).lower().split()
    families = [
        ("pacman", {"arch", "cachyos", "manjaro", "endeavouros", "garuda", "artix"}),
        ("apt", {"debian", "ubuntu", "linuxmint", "pop", "elementary", "zorin", "neon"}),
        ("dnf", {"fedora", "rhel", "centos", "nobara", "bazzite", "ultramarine"}),
        ("zypper", {"opensuse", "suse", "opensuse-tumbleweed", "opensuse-leap"}),
    ]
    for pkg, names in families:
        if any(i in names for i in ids):
            return pkg
    for pkg in ("pacman", "apt", "dnf", "zypper"):
        if which(pkg):
            return pkg
    return None


def install_command(pkg: str | None, what: str, gpu: str = "") -> str:
    key = f"{what}-{gpu}" if what == "vulkan32" else what
    table = PACKAGES[key]
    spec = table.get(pkg) if pkg else None
    if spec is None:
        spec = table.get(None)
    if spec is None:
        return f"Install {what} with your distro's package manager."
    if spec.startswith("!"):
        return spec[1:]
    return f"{INSTALL[pkg]} {spec}"


MULTILIB_FIX = ("sudo sed -i '/^#\\[multilib\\]/,/^#Include/ s/^#//' /etc/pacman.conf && sudo pacman -Syu")


def multilib_enabled(pacman_conf: str) -> bool:
    return any(line.strip() == "[multilib]" for line in pacman_conf.splitlines())


def terminal_command(command: str, which: Callable[[str], str | None] = shutil.which,
                     env: dict | None = None) -> list[str] | None:
    env = os.environ if env is None else env
    script = f'{command}; echo; read -r -p "Done. Press Enter to close." _'
    preferred = env.get("TERMINAL")
    if preferred and which(preferred):
        return [preferred, "-e", "bash", "-c", script]
    for name, flags in TERMINALS:
        if which(name):
            return [name, *flags, "bash", "-c", script]
    return None


def _read(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _gpu_names() -> dict[str, str]:
    try:
        out = subprocess.run(["lspci", "-mm"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return {}
    names = {}
    for line in out.splitlines():
        try:
            parts = shlex.split(line)
        except ValueError:
            continue
        if len(parts) >= 4 and ("VGA" in parts[1] or "3D" in parts[1] or "Display" in parts[1]):
            vendor = next((v for k, v in (("NVIDIA", "nvidia"), ("AMD", "amd"), ("ATI", "amd"), ("Intel", "intel"))
                           if k in parts[2]), None)
            if vendor:
                model = parts[3]
                if "[" in model and "]" in model:
                    model = model[model.rfind("[") + 1:model.rfind("]")]
                names.setdefault(vendor, model)
    return names


def detect() -> SystemInfo:
    info = SystemInfo()
    info.os_release = parse_os_release(_read("/etc/os-release"))
    info.distro = info.os_release.get("PRETTY_NAME") or info.os_release.get("NAME") or "Linux"
    info.pkg = package_manager(info.os_release)

    vendors = []
    for card in sorted(Path("/sys/class/drm").glob("card[0-9]*")):
        v = VENDORS.get(_read(str(card / "device/vendor")))
        if v and v not in vendors:
            vendors.append(v)
    for v in ("nvidia", "amd", "intel"):
        if v in vendors:
            info.gpu = v
            break
    info.laptop = any(p.name.startswith("BAT") for p in Path("/sys/class/power_supply").glob("*"))
    info.hybrid = info.laptop and len(vendors) > 1
    names = _gpu_names()
    info.gpu_name = names.get(info.gpu, "")
    if info.gpu == "nvidia":
        info.driver = _read("/sys/module/nvidia/version")
    info.session = os.environ.get("XDG_SESSION_TYPE", "")
    info.desktop = os.environ.get("XDG_CURRENT_DESKTOP", "")
    for line in _read("/proc/cpuinfo").splitlines():
        if line.startswith("model name"):
            info.cpu = line.split(":", 1)[1].strip()
            break
    for line in _read("/proc/meminfo").splitlines():
        if line.startswith("MemTotal"):
            info.ram_gb = round(int(line.split()[1]) / 1024 / 1024)
            break
    info.kernel = os.uname().release
    return info


def _lib32(*names: str) -> bool:
    for d in LIB32_DIRS:
        for n in names:
            if list(d.glob(n)):
                # /usr/lib holds 64-bit libs on Arch and Debian, 32-bit only on Fedora-style layouts.
                if d == Path("/usr/lib") and not Path("/usr/lib64").is_dir():
                    continue
                return True
    return False


def _in_group(name: str) -> bool | None:
    try:
        group = grp.getgrnam(name)
    except KeyError:
        return None
    return group.gr_gid in os.getgroups() or os.environ.get("USER", "") in group.gr_mem


def tools_available() -> set[str]:
    return {t for t in ("gamemoderun", "game-performance", "mangohud", "protontricks", "prime-run") if shutil.which(t)}


def checks(info: SystemInfo, root: steam.SteamRoot | None, overlay_on: bool, risky_on: bool,
           ge_latest: str | None = None) -> list[Check]:
    out: list[Check] = []
    pkg = info.pkg

    if root is None:
        out.append(Check("steam", "Steam", False, "Steam wasn't found. Install it and log in once, then refresh."))
    else:
        libs = steam.libraries(root)
        kind = {"native": "", "flatpak": " (Flatpak)", "snap": " (Snap)"}[root.kind]
        out.append(Check("steam", "Steam", True, f"Found{kind}, {len(libs)} game folder{'s' if len(libs) != 1 else ''}."))

    gpu = GPU_NAMES[info.gpu] + (f" {info.gpu_name}" if info.gpu_name else "")
    if info.gpu == "nvidia":
        try:
            major = int(info.driver.split(".")[0])
        except ValueError:
            major = 0
        if major and major < 550:
            out.append(Check("driver", gpu, False, f"Driver {info.driver} is old. 550 or newer runs Proton games much better."))
        else:
            out.append(Check("driver", gpu, True, f"Driver {info.driver or 'found'}."))
        if info.session == "wayland" and _read("/sys/module/nvidia_drm/parameters/modeset") not in ("Y", "1"):
            out.append(Check("modeset", "NVIDIA on Wayland", False,
                             "nvidia_drm.modeset is off. Games on Wayland may stutter or not start.",
                             "Add nvidia_drm.modeset=1 to your kernel parameters, then reboot."))
    else:
        out.append(Check("driver", gpu, None if info.gpu == "unknown" else True,
                         "Using the open source Mesa driver." if info.gpu != "unknown" else "Couldn't tell which GPU you have."))

    if pkg == "pacman" and not multilib_enabled(_read("/etc/pacman.conf")):
        out.append(Check("multilib", "32-bit packages (multilib)", False,
                         "The multilib repo is off in /etc/pacman.conf, so 32-bit GameMode and graphics "
                         "packages can't be installed. Steam itself needs it too.", MULTILIB_FIX))

    if root is None or root.kind == "native":
        if info.gpu == "nvidia":
            has32 = _lib32("libnvidia-glcore.so*", "libGLX_nvidia.so.0")
        else:
            has32 = any(Path("/usr/share/vulkan/icd.d").glob("*i686*.json")) if info.gpu in ("amd", "intel") else True
        if info.gpu != "unknown":
            out.append(Check("vulkan32", "32-bit graphics driver", has32,
                             "Found." if has32 else "Missing. Older 32-bit games and some launchers won't start without it.",
                             None if has32 else install_command(pkg, "vulkan32", info.gpu)))

    gm = shutil.which("gamemoderun") is not None
    gm32 = _lib32("libgamemodeauto.so.0")
    if gm and gm32:
        out.append(Check("gamemode", "GameMode", True, "Installed. Games get a performance boost while running."))
    else:
        out.append(Check("gamemode", "GameMode", False,
                         "Not installed. It's the main FPS tweak mrrpmeowfix adds to every game." if not gm
                         else "The 32-bit part is missing, so 32-bit games won't get the boost.",
                         install_command(pkg, "gamemode")))
    member = _in_group("gamemode")
    if gm and member is False:
        out.append(Check("gamemode-group", "GameMode permissions", False,
                         "You're not in the gamemode group, so GameMode can't raise game priority.",
                         "sudo usermod -aG gamemode $USER   # then log out and back in"))

    if overlay_on:
        mh = shutil.which("mangohud") is not None
        out.append(Check("mangohud", "MangoHud", mh, "Installed." if mh else "Needed for the FPS overlay.",
                         None if mh else install_command(pkg, "mangohud")))
    if risky_on:
        pt = shutil.which("protontricks") is not None
        out.append(Check("protontricks", "protontricks", pt,
                         "Installed." if pt else "Needed to install Windows components for risky fixes.",
                         None if pt else install_command(pkg, "protontricks")))

    if root is not None:
        tool = steam.newest_ge(steam.compat_tools(root))
        if tool is None:
            out.append(Check("ge", "GE-Proton", False,
                             "Not installed. Many games run better on it, and mrrpmeowfix picks it where players recommend it.",
                             action="install-ge"))
        elif ge_latest and not any(t.internal_name.startswith(ge_latest) for t in steam.compat_tools(root)):
            out.append(Check("ge", "GE-Proton", False, f"{tool.display} installed, {ge_latest} is out.", action="install-ge"))
        else:
            out.append(Check("ge", "GE-Proton", True, f"{tool.display} installed."))

    try:
        count = int(_read("/proc/sys/vm/max_map_count") or 0)
    except ValueError:
        count = 0
    ok = count >= MAP_COUNT_WANTED
    out.append(Check("mapcount", "Memory map limit", ok,
                     "High enough for big games." if ok else
                     f"vm.max_map_count is {count}. Some big games crash on load with a low value.",
                     None if ok else MAP_COUNT_FIX))

    if info.hybrid:
        out.append(Check("hybrid", "Laptop with two GPUs", None,
                         "Games should run on the faster GPU. mrrpmeowfix adds prime-run on NVIDIA laptops."))
    return out
