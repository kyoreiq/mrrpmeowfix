from __future__ import annotations

import threading
import traceback
from typing import Any, Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk, Pango  # noqa: E402


class FixedPicture(Gtk.Picture):
    """A picture that asks for a fixed size instead of the image's own size."""

    def __init__(self, width: int = 0, height: int = 0, **kw):
        super().__init__(content_fit=Gtk.ContentFit.COVER, can_shrink=True, **kw)
        self._w, self._h = width, height

    def do_measure(self, orientation, for_size):
        size = self._w if orientation == Gtk.Orientation.HORIZONTAL else self._h
        return size, size, -1, -1


def run_async(work: Callable[[], Any], done: Callable[[Any], None] | None = None,
              failed: Callable[[BaseException], None] | None = None) -> None:
    def target():
        try:
            result = work()
        except BaseException as e:  # shown to the user, never swallowed
            traceback.print_exc()
            if failed:
                GLib.idle_add(lambda: failed(e) and False)
            return
        if done:
            GLib.idle_add(lambda: done(result) and False)

    threading.Thread(target=target, daemon=True).start()


def on_main(fn: Callable, *args) -> None:
    GLib.idle_add(lambda: fn(*args) and False)


def label(text: str = "", *classes: str, wrap: bool = False, xalign: float = 0.0,
          selectable: bool = False, ellipsize: bool = False, lines: int = 0) -> Gtk.Label:
    lab = Gtk.Label(label=text, xalign=xalign, wrap=wrap, selectable=selectable)
    if wrap:
        lab.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    if ellipsize:
        lab.set_ellipsize(Pango.EllipsizeMode.END)
    if lines:
        lab.set_lines(lines)
    for c in classes:
        lab.add_css_class(c)
    return lab


def esc(text: str) -> str:
    return GLib.markup_escape_text(text or "")


def clear(box: Gtk.Widget) -> None:
    child = box.get_first_child()
    while child is not None:
        nxt = child.get_next_sibling()
        box.remove(child)
        child = nxt


def vbox(spacing: int = 0, *classes: str) -> Gtk.Box:
    b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)
    for c in classes:
        b.add_css_class(c)
    return b


def hbox(spacing: int = 0, *classes: str) -> Gtk.Box:
    b = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=spacing)
    for c in classes:
        b.add_css_class(c)
    return b


def plural(n: int, word: str, many: str | None = None) -> str:
    return f"{n} {word if n == 1 else (many or word + 's')}"


TIER_NAMES = {
    "platinum": "Platinum", "gold": "Gold", "silver": "Silver", "bronze": "Bronze",
    "borked": "Borked", "native": "Native", "pending": "Pending",
}


def tier_pill(tier: str | None) -> Gtk.Label:
    key = tier if tier in TIER_NAMES else None
    lab = label(TIER_NAMES.get(tier or "", "No reports"), "tier", f"tier-{key or 'none'}")
    return lab


def page_head(title: str, subtitle: str = "") -> tuple[Gtk.Box, Gtk.Label]:
    box = vbox(4)
    box.append(label(title, "page-title"))
    sub = label(subtitle, "page-sub", wrap=True)
    box.append(sub)
    return box, sub


def show_error(parent: Gtk.Widget, heading: str, body: str) -> None:
    dialog = Adw.AlertDialog(heading=heading, body=body)
    dialog.add_response("ok", "OK")
    dialog.present(parent)
