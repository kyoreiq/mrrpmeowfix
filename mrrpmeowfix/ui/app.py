from __future__ import annotations

import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, PangoCairo  # noqa: E402

from .. import paths  # noqa: E402

MIN_ADW = (1, 5)


def load_fonts() -> None:
    fontmap = PangoCairo.FontMap.get_default()
    if not hasattr(fontmap, "add_font_file"):
        return  # older Pango: the installer puts the fonts in ~/.local/share/fonts instead
    for font in sorted(paths.bundled("fonts").glob("*.ttf")):
        try:
            fontmap.add_font_file(str(font))
        except GLib.Error:
            pass


def load_css() -> None:
    provider = Gtk.CssProvider()
    provider.load_from_path(str(Path(__file__).with_name("style.css")))
    Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                              Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=paths.APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        GLib.set_application_name("mrrpmeowfix")

    def do_activate(self):
        win = self.props.active_window
        if win is None:
            from ..core import Service
            from .window import MainWindow

            Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
            load_fonts()
            load_css()
            Gtk.Window.set_default_icon_name(paths.APP_ID)
            win = MainWindow(self, Service())
        win.present()


def main() -> int:
    if (Adw.get_major_version(), Adw.get_minor_version()) < MIN_ADW:
        print(f"mrrpmeowfix needs libadwaita {MIN_ADW[0]}.{MIN_ADW[1]} or newer, this system has "
              f"{Adw.get_major_version()}.{Adw.get_minor_version()}.", file=sys.stderr)
        return 1
    return App().run(sys.argv)
