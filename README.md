# mrrpmeowfix

Fixes and FPS tweaks for your Steam games on Linux, without digging through ProtonDB yourself.

It finds every Steam game on every drive, looks at what other players with the same GPU brand used to
get each game running well, and puts those settings into Steam for you. Pick one game or a bunch, press
**Apply fixes**, done. Every change can be undone.

## Install

Unzip it, open a terminal in the folder and run:

```
bash install.sh
```

It checks for Python, GTK 4 and libadwaita and offers to install them if they're missing (Arch, CachyOS,
Manjaro, EndeavourOS, Fedora, Ubuntu, Mint, Debian 13+ and openSUSE Tumbleweed). After that, mrrpmeowfix is
in your app menu.

## Using it

- **Library** shows your installed games. New installs show up by themselves. Tick the games you want and
  press **Apply fixes**, or click a game to see exactly what it would change and why.
- **All games** lets you look up any game in the ProtonDB data, even ones you don't own.
- **Your PC** checks your drivers, GameMode, GE-Proton and a few system settings, and gives you the command
  to fix anything that's missing.
- **Settings** has the Risky fixes switch, the FPS overlay and a few other options.

Steam has to be closed while its settings are written, so mrrpmeowfix closes it and opens it again for you.

## What it changes

- Launch options: GameMode, the shader cache settings for your GPU, NVIDIA DLSS support, and whatever
  launch options most players used for that game.
- The Proton version, when most players say a game runs better on GE-Proton or Proton Experimental.
- Your own launch options are never removed. If you set a Proton version for a game yourself, it's left alone.

## Risky fixes

Off by default. Turning it on lets mrrpmeowfix switch Proton on games with anti-cheat, install Windows
components into a game with protontricks, and use experimental options. Some of that can break online play.

Turn it off and press **Apply fixes** again to remove the risky fixes it added and keep the normal ones.
Windows components that were installed can't be removed automatically.

## Undo and backups

Every game page has **Undo fixes**. A copy of Steam's settings files is saved before every change
(Settings, Open backups folder). The last 10 are kept.

## Updates

mrrpmeowfix keeps itself up to date. A few times a day it checks for a new version and installs it in the
background; restart the app to use it. Turn this off in Settings, Updates.

It also picks up the shared fix list every few hours. That's how a fix for a game that broke yesterday reaches
everyone without waiting for a new version or for ProtonDB's monthly data.

## Uninstall

```
bash uninstall.sh
```

Fixes already applied stay in Steam. Use Undo in the app first if you want them gone.

## Where the data comes from

- [ProtonDB](https://www.protondb.com) public report data (updated monthly, mrrpmeowfix checks about once a week)
- [AreWeAntiCheatYet](https://areweanticheatyet.com) for anti-cheat info
- Fonts: Space Grotesk and JetBrains Mono, both under the SIL Open Font License (see `data/fonts`)

## For whoever runs the GitHub repo

**Adding a fix for a game:** edit `fixes/community.json` (the pencil icon on GitHub works fine) and commit.
Every copy picks it up within about 6 hours. Example:

```json
"games": {
  "2406770": {
    "add": ["-dx11"],
    "block": ["PROTON_USE_WINED3D"],
    "proton": "ge",
    "note": "Crashes on start without -dx11 since the November patch."
  }
}
```

The key is the Steam app ID (it's in the game's store page URL). `add` takes launch options, `block` takes
launch options, setting names or Windows components that should never be applied, `proton` is `ge`,
`experimental` or `default`, and `note` shows on the game's page. Everything still goes through the same safety
rules: shell commands are dropped, risky options stay behind the Risky fixes switch, and anti-cheat games only
get safe tweaks.

**Publishing a new version:** `./release.sh 1.2.0 "What changed"`. It runs the tests, builds the zip with its
checksum, pushes and creates the GitHub release. Needs the GitHub CLI (`sudo pacman -S github-cli`, then
`gh auth login`).
