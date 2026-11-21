#!/usr/bin/env bash
# Removes mrrpmeowfix. Fixes already applied to games stay; use Undo in the app first if you want them gone.
set -euo pipefail

DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
CACHE_HOME="${XDG_CACHE_HOME:-$HOME/.cache}"

rm -rf "$DATA_HOME/mrrpmeowfix/app"
rm -f "$HOME/.local/bin/mrrpmeowfix"
rm -f "$DATA_HOME/applications/io.github.mrrpmeowfix.desktop"
rm -f "$DATA_HOME/icons/hicolor/scalable/apps/io.github.mrrpmeowfix.svg"
rm -rf "$DATA_HOME/fonts/mrrpmeowfix"
rm -rf "$CACHE_HOME/mrrpmeowfix"
command -v fc-cache >/dev/null && fc-cache -f >/dev/null 2>&1 || true

echo "mrrpmeowfix is removed."
if [ -d "$DATA_HOME/mrrpmeowfix" ] || [ -d "$CONFIG_HOME/mrrpmeowfix" ]; then
    echo "Your settings, the list of applied fixes and the Steam backups are still in:"
    echo "    $DATA_HOME/mrrpmeowfix"
    echo "    $CONFIG_HOME/mrrpmeowfix"
    read -r -p "Delete those too? [y/N] " answer
    case "${answer:-n}" in
        [Yy]*) rm -rf "$DATA_HOME/mrrpmeowfix" "$CONFIG_HOME/mrrpmeowfix"; echo "Deleted." ;;
        *) echo "Kept." ;;
    esac
fi
