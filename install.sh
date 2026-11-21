#!/usr/bin/env bash
# Installs mrrpmeowfix for the current user. No root needed except for missing system packages.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
APP_DIR="$DATA_HOME/mrrpmeowfix/app"
BIN_DIR="$HOME/.local/bin"
LAUNCHER="$BIN_DIR/mrrpmeowfix"
DESKTOP="$DATA_HOME/applications/io.github.mrrpmeowfix.desktop"
ICON_DIR="$DATA_HOME/icons/hicolor/scalable/apps"
FONT_DIR="$DATA_HOME/fonts/mrrpmeowfix"

blue() { printf '\033[38;2;169;209;255m%s\033[0m\n' "$*"; }
warn() { printf '\033[38;2;242;197;139m%s\033[0m\n' "$*"; }

if [ "$(id -u)" -eq 0 ]; then
    warn "Run this as your normal user, not with sudo. It will ask for sudo itself if it needs to install packages."
    exit 1
fi

. /etc/os-release 2>/dev/null || true
ids=" ${ID:-} ${ID_LIKE:-} "
pkg=""
case "$ids" in
    *" arch "*|*" cachyos "*|*" manjaro "*|*" endeavouros "*|*" garuda "*|*" artix "*) pkg=pacman ;;
    *" debian "*|*" ubuntu "*|*" linuxmint "*|*" pop "*) pkg=apt ;;
    *" fedora "*|*" rhel "*|*" nobara "*|*" bazzite "*) pkg=dnf ;;
    *" opensuse "*|*" suse "*|*"opensuse-tumbleweed"*) pkg=zypper ;;
esac
if [ -z "$pkg" ]; then
    for m in pacman apt dnf zypper; do command -v "$m" >/dev/null && { pkg=$m; break; }; done
fi

blue "mrrpmeowfix installer"
echo "System: ${PRETTY_NAME:-Linux}"

check_deps() {
    python3 - <<'PY' 2>/dev/null
import sys
assert sys.version_info >= (3, 10)
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk
assert (Adw.get_major_version(), Adw.get_minor_version()) >= (1, 5)
PY
}

if ! check_deps; then
    case "$pkg" in
        pacman) cmd="sudo pacman -S --needed python python-gobject gtk4 libadwaita" ;;
        apt)    cmd="sudo apt install python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1" ;;
        dnf)    cmd="sudo dnf install python3 python3-gobject gtk4 libadwaita" ;;
        zypper) cmd="sudo zypper install python3 python3-gobject typelib-1_0-Gtk-4_0 typelib-1_0-Adw-1" ;;
        *)      cmd="" ;;
    esac
    warn "Some things mrrpmeowfix needs are missing: Python 3.10+, PyGObject, GTK 4 and libadwaita 1.5+."
    if [ -n "$cmd" ]; then
        echo "This installs them:"
        echo "    $cmd"
        read -r -p "Run it now? [Y/n] " answer
        case "${answer:-y}" in
            [Yy]*) $cmd ;;
            *) echo "Install them yourself and run ./install.sh again."; exit 1 ;;
        esac
    else
        echo "Install them with your package manager, then run ./install.sh again."
        exit 1
    fi
    if ! check_deps; then
        warn "Still missing something. Your distro may ship a libadwaita older than 1.5, which is too old."
        exit 1
    fi
fi

echo "Copying files"
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR" "$BIN_DIR" "$(dirname "$DESKTOP")" "$ICON_DIR" "$FONT_DIR"
cp -r "$HERE/mrrpmeowfix" "$HERE/data" "$APP_DIR/"
find "$APP_DIR" -name '__pycache__' -type d -prune -exec rm -rf {} +

cat > "$LAUNCHER" <<SH
#!/bin/sh
export PYTHONPATH="$APP_DIR"
exec python3 -m mrrpmeowfix "\$@"
SH
chmod +x "$LAUNCHER"

sed "s|@EXEC@|$LAUNCHER|" "$HERE/data/io.github.mrrpmeowfix.desktop" > "$DESKTOP"
cp "$HERE/data/icons/io.github.mrrpmeowfix.svg" "$ICON_DIR/"
cp "$HERE"/data/fonts/*.ttf "$FONT_DIR/"

command -v fc-cache >/dev/null && fc-cache -f "$FONT_DIR" >/dev/null 2>&1 || true
command -v update-desktop-database >/dev/null && update-desktop-database "$(dirname "$DESKTOP")" >/dev/null 2>&1 || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t "$DATA_HOME/icons/hicolor" >/dev/null 2>&1 || true

blue "Done."
echo "Open mrrpmeowfix from your app menu, or run: mrrpmeowfix"
case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) warn "Note: $BIN_DIR isn't in your PATH, so the command only works as $LAUNCHER. The app menu entry works either way." ;;
esac
