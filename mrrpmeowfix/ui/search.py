from __future__ import annotations

from typing import Callable

from gi.repository import Adw, GLib, Gtk

from ..index import GameStats
from .util import clear, hbox, label, page_head, plural, tier_pill, vbox


class SearchPage(Adw.NavigationPage):
    def __init__(self, search: Callable[[str], list[GameStats]], installed: Callable[[], set[int]],
                 on_open: Callable[[GameStats], None], total_games: int):
        super().__init__(title="All games", tag="search")
        self.search_fn = search
        self.installed = installed
        self.on_open = on_open
        self._pending = 0

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar(show_title=False, show_start_title_buttons=False))
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        clamp = Adw.Clamp(maximum_size=860)
        body = vbox(18)
        body.set_margin_start(28)
        body.set_margin_end(28)
        body.set_margin_bottom(40)
        head, self.subtitle = page_head("All games", "")
        self.set_total(total_games)
        body.append(head)

        self.entry = Gtk.SearchEntry(placeholder_text="Game name or Steam app ID, like Bodycam or 730")
        self.entry.set_size_request(-1, 44)
        self.entry.connect("search-changed", self._changed)
        self.entry.connect("activate", lambda *_: self._run())
        body.append(self.entry)

        self.results = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.results.add_css_class("boxed-list")
        self.results.set_visible(False)
        self.results.connect("row-activated", lambda _lb, row: self.on_open(row.stats))
        body.append(self.results)
        self.hint = label("", "muted", wrap=True)
        body.append(self.hint)

        clamp.set_child(body)
        scroller.set_child(clamp)
        toolbar.set_content(scroller)
        self.set_child(toolbar)

    def set_total(self, total: int) -> None:
        self.subtitle.set_text(
            f"Look up what mrrpmeowfix would change for any of the {total:,} games in the ProtonDB data, "
            "including ones you don't own.")

    def focus(self) -> None:
        self.entry.grab_focus()

    def _changed(self, *_):
        self._pending += 1
        ticket = self._pending
        GLib.timeout_add(180, lambda: self._run() if ticket == self._pending else None)

    def _run(self) -> None:
        text = self.entry.get_text().strip()
        clear(self.results)
        if not text:
            self.results.set_visible(False)
            self.hint.set_text("")
            return
        hits = self.search_fn(text)
        if not hits:
            self.results.set_visible(False)
            self.hint.set_text(f"No game matching “{text}” in the report data yet.")
            return
        owned = self.installed()
        for stats in hits:
            row = Adw.ActionRow(title=GLib.markup_escape_text(stats.title), activatable=True)
            row.stats = stats
            row.set_subtitle(f"{plural(stats.total, 'report')}, Steam app {stats.appid}")
            if stats.appid in owned:
                chip = label("Installed", "chip", "accent")
                chip.set_valign(Gtk.Align.CENTER)
                row.add_suffix(chip)
            pill = tier_pill(stats.rough_tier())
            pill.set_valign(Gtk.Align.CENTER)
            row.add_suffix(pill)
            row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
            self.results.append(row)
        self.results.set_visible(True)
        self.hint.set_text("" if len(hits) < 60 else "Showing the first 60 matches. Type more to narrow it down.")
