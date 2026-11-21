"""Builds a small Steam install in a temp folder for tests."""

from __future__ import annotations

import tempfile
from pathlib import Path

ACCOUNT_ID64 = "76561198000000001"
ACCOUNT_ID = 39734273


def _w(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def manifest(appid: int, name: str, installdir: str, flags: int = 4) -> str:
    return (
        '"AppState"\n{\n'
        f'\t"appid"\t\t"{appid}"\n'
        f'\t"name"\t\t"{name}"\n'
        f'\t"installdir"\t\t"{installdir}"\n'
        '\t"SizeOnDisk"\t\t"1000"\n'
        f'\t"StateFlags"\t\t"{flags}"\n'
        "}\n"
    )


def build(launch_options: dict[int, str] | None = None) -> tuple[tempfile.TemporaryDirectory, Path, Path]:
    tmp = tempfile.TemporaryDirectory()
    base = Path(tmp.name)
    root = base / "home/.local/share/Steam"
    lib2 = base / "disk/SteamLibrary"

    _w(
        root / "steamapps/libraryfolders.vdf",
        '"libraryfolders"\n{\n'
        f'\t"0"\n\t{{\n\t\t"path"\t\t"{root}"\n\t\t"apps"\n\t\t{{\n\t\t}}\n\t}}\n'
        f'\t"1"\n\t{{\n\t\t"path"\t\t"{lib2}"\n\t\t"apps"\n\t\t{{\n\t\t}}\n\t}}\n'
        "}\n",
    )
    _w(root / "steamapps/appmanifest_438100.acf", manifest(438100, "VRChat", "VRChat"))
    _w(root / "steamapps/appmanifest_1493710.acf", manifest(1493710, "Proton Experimental", "Proton - Experimental"))
    _w(root / "steamapps/appmanifest_1628350.acf", manifest(1628350, "Steam Linux Runtime 3.0 (sniper)", "SteamLinuxRuntime_sniper"))
    (root / "steamapps/common/VRChat/EasyAntiCheat").mkdir(parents=True)
    (root / "steamapps/common/Proton - Experimental").mkdir(parents=True)
    _w(lib2 / "steamapps/appmanifest_107410.acf", manifest(107410, "Arma 3", "Arma 3"))
    _w(lib2 / "steamapps/appmanifest_602960.acf", manifest(602960, "Barotrauma", "Barotrauma"))
    _w(lib2 / "steamapps/appmanifest_2406770.acf", manifest(2406770, "Bodycam", "Bodycam", flags=1026))
    (lib2 / "steamapps/common/Arma 3").mkdir(parents=True)
    (lib2 / "steamapps/common/Barotrauma").mkdir(parents=True)
    (root / "steamapps/compatdata/107410").mkdir(parents=True)
    (root / "steamapps/compatdata/438100").mkdir(parents=True)

    _w(
        root / "config/loginusers.vdf",
        '"users"\n{\n'
        '\t"76561197960265729"\n\t{\n\t\t"PersonaName"\t\t"other"\n\t\t"AutoLogin"\t\t"0"\n\t\t"timestamp"\t\t"1700000000"\n\t}\n'
        f'\t"{ACCOUNT_ID64}"\n\t{{\n\t\t"PersonaName"\t\t"player"\n\t\t"AutoLogin"\t\t"1"\n\t\t"timestamp"\t\t"1795263957"\n\t}}\n'
        "}\n",
    )
    _w(
        root / "config/config.vdf",
        '"InstallConfigStore"\n{\n\t"Software"\n\t{\n\t\t"Valve"\n\t\t{\n\t\t\t"Steam"\n\t\t\t{\n'
        '\t\t\t\t"CompatToolMapping"\n\t\t\t\t{\n'
        '\t\t\t\t\t"438100"\n\t\t\t\t\t{\n\t\t\t\t\t\t"name"\t\t"proton-cachyos-slr"\n\t\t\t\t\t\t"config"\t\t""\n\t\t\t\t\t\t"priority"\t\t"250"\n\t\t\t\t\t}\n'
        "\t\t\t\t}\n\t\t\t}\n\t\t}\n\t}\n}\n",
    )
    apps = ""
    for appid, opts in (launch_options or {}).items():
        esc = opts.replace("\\", "\\\\").replace('"', '\\"')
        apps += f'\t\t\t\t\t"{appid}"\n\t\t\t\t\t{{\n\t\t\t\t\t\t"LaunchOptions"\t\t"{esc}"\n\t\t\t\t\t}}\n'
    _w(
        root / f"userdata/{ACCOUNT_ID}/config/localconfig.vdf",
        '"UserLocalConfigStore"\n{\n\t"Software"\n\t{\n\t\t"Valve"\n\t\t{\n\t\t\t"Steam"\n\t\t\t{\n'
        f'\t\t\t\t"apps"\n\t\t\t\t{{\n{apps}\t\t\t\t}}\n'
        "\t\t\t}\n\t\t}\n\t}\n}\n",
    )
    _w(
        root / "compatibilitytools.d/GE-Proton11-7-x86_64/compatibilitytool.vdf",
        '"compatibilitytools"\n{\n  "compat_tools"\n  {\n    "GE-Proton11-7-x86_64" // Internal name\n'
        '    {\n      "display_name" "GE-Proton11-7"\n    }\n  }\n}\n',
    )
    _w(
        root / "compatibilitytools.d/GE-Proton11-11-x86_64/compatibilitytool.vdf",
        '"compatibilitytools"\n{\n  "compat_tools"\n  {\n    "GE-Proton11-11-x86_64"\n'
        '    {\n      "display_name" "GE-Proton11-11"\n    }\n  }\n}\n',
    )
    _w(root / "appcache/librarycache/438100/library_600x900.jpg", "jpg")
    return tmp, root, lib2
