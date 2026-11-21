from __future__ import annotations

from typing import Callable

from gi.repository import Adw, Gtk

from ..core import GameView
from . import art
from .util import FixedPicture, clear, hbox, label, page_head, plural, tier_pill, vbox

COVER_W, COVER_H = 168, 252

STATUS_TEXT = {
    "ready": lambda n: plural(n, "fix", "fixes") + " ready",
    "new": lambda n: plural(n, "change") + " waiting",
    "fixed": lambda n: "Fixed",
    "nothing": lambda n: "Nothing to change",
}


class GameCard(Gtk.Box):
    def __init__(self, view: GameView, root, on_open: Callable[[GameView], None],
                 on_toggle: Callable[[int, bool], None], selected: bool):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, halign=Gtk.Align.CENTER, valign=Gtk.Align.START)
        self.view = view
        self.set_size_request(COVER_W, -1)
        self.add_css_class("cover-card")
        self._on_toggle = on_toggle

        frame = Gtk.Overlay()
        frame.add_css_class("cover-frame")
        frame.set_overflow(Gtk.Overflow.HIDDEN)
        frame.set_size_request(COVER_W, COVER_H)
        self.picture = FixedPicture(COVER_W, COVER_H)
        placeholder = label(view.name, "cover-placeholder", wrap=True, xalign=0)
        placeholder.set_max_width_chars(12)
        placeholder.set_valign(Gtk.Align.END)
        self.stack = Gtk.Stack()
        self.stack.add_named(placeholder, "text")
        self.stack.add_named(self.picture, "art")
        frame.set_child(self.stack)

        self.check = Gtk.CheckButton(active=selected)
        self.check.add_css_class("cover-check")
        self.check.set_halign(Gtk.Align.START)
        self.check.set_valign(Gtk.Align.START)
        self.check.set_tooltip_text("Select for Apply fixes")
        self.check.connect("toggled", self._toggled)
        frame.add_overlay(self.check)

        pill = tier_pill(view.tier)
        pill.set_halign(Gtk.Align.END)
        pill.set_valign(Gtk.Align.START)
        frame.add_overlay(pill)

        click = Gtk.GestureClick()
        click.connect("released", lambda *_: on_open(self.view))
        self.stack.add_controller(click)
        self.stack.set_cursor_from_name("pointer")

        self.append(frame)
        title = label(view.name, "game-title", ellipsize=True)
        title.set_max_width_chars(18)
        title.set_tooltip_text(view.name)
        self.append(title)
        status = label(STATUS_TEXT[view.status](view.pending), "status", f"status-{view.status}", ellipsize=True)
        self.append(status)
        self.set_selected_style(selected)

        art.load(root, view.appid, ["library_600x900"], COVER_W * 2, COVER_H * 2, self._art)

    def _art(self, texture) -> None:
        if texture is not None:
            self.picture.set_paintable(texture)
            self.stack.set_visible_child_name("art")

    def _toggled(self, button: Gtk.CheckButton) -> None:
        self.set_selected_style(button.get_active())
        self._on_toggle(self.view.appid, button.get_active())

    def set_selected_style(self, on: bool) -> None:
        if on:
            self.add_css_class("selected")
        else:
            self.remove_css_class("selected")


class LibraryPage(Adw.NavigationPage):
    def __init__(self, on_open: Callable[[GameView], None], on_apply: Callable[[list[int]], None],
                 on_refresh: Callable[[], None]):
        super().__init__(title="Library", tag="library")
        self.on_open = on_open
        self.on_apply = on_apply
        self.views: list[GameView] = []
        self.selected: set[int] = set()
        self.cards: dict[int, GameCard] = {}
        self.root = None

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar(show_title=False, show_start_title_buttons=False)
        refresh = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Scan for games again")
        refresh.connect("clicked", lambda *_: on_refresh())
        header.pack_end(refresh)
        self.filter = Gtk.SearchEntry(placeholder_text="Filter games")
        self.filter.set_size_request(220, -1)
        self.filter.connect("search-changed", lambda *_: self.grid.invalidate_filter())
        header.pack_end(self.filter)
        toolbar.add_top_bar(header)

        overlay = Gtk.Overlay()
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        body = vbox(22)
        body.set_margin_start(36)
        body.set_margin_end(36)
        body.set_margin_top(8)
        body.set_margin_bottom(120)

        head_row = hbox(12)
        head, self.subtitle = page_head("Library", "Looking for your Steam games")
        head.set_hexpand(True)
        head_row.append(head)
        self.select_needed = Gtk.Button(label="Select all that need fixes", valign=Gtk.Align.END)
        self.select_needed.add_css_class("quiet")
        self.select_needed.connect("clicked", lambda *_: self.select_where_needed())
        head_row.append(self.select_needed)
        body.append(head_row)

        self.empty = Adw.StatusPage(icon_name="applications-games-symbolic", vexpand=True)
        self.empty.set_visible(False)
        body.append(self.empty)

        self.grid = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                                column_spacing=26, row_spacing=30, min_children_per_line=1,
                                max_children_per_line=12, valign=Gtk.Align.START, halign=Gtk.Align.START)
        self.grid.set_filter_func(self._filter)
        body.append(self.grid)
        scroller.set_child(body)
        overlay.set_child(scroller)

        self.bar = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_UP,
                                valign=Gtk.Align.END, halign=Gtk.Align.CENTER)
        bar = hbox(10, "applybar")
        self.count = label("", "applybar-count")
        self.count.set_valign(Gtk.Align.CENTER)
        self.count.set_margin_end(14)
        bar.append(self.count)
        clear_btn = Gtk.Button(label="Clear")
        clear_btn.add_css_class("flat")
        clear_btn.connect("clicked", lambda *_: self.set_selection(set()))
        bar.append(clear_btn)
        apply_btn = Gtk.Button(label="Apply fixes")
        apply_btn.add_css_class("pill-accent")
        apply_btn.connect("clicked", lambda *_: self.on_apply(sorted(self.selected)))
        bar.append(apply_btn)
        self.bar.set_child(bar)
        overlay.add_overlay(self.bar)

        toolbar.set_content(overlay)
        self.set_child(toolbar)

    def _filter(self, child: Gtk.FlowBoxChild) -> bool:
        text = self.filter.get_text().strip().lower()
        card = child.get_child()
        return not text or text in card.view.name.lower()

    def show_message(self, title: str, body: str) -> None:
        self.empty.set_title(title)
        self.empty.set_description(body)
        self.empty.set_visible(True)
        self.subtitle.set_text("")
        self.grid.set_visible(False)
        self.select_needed.set_visible(False)

    def set_views(self, views: list[GameView], root, libraries: int) -> None:
        self.views = views
        self.root = root
        ids = {v.appid for v in views}
        self.selected &= ids
        clear(self.grid)
        self.cards.clear()
        if not views:
            self.subtitle.set_text("")
            self.show_message("No games found", "Install a game in Steam and it shows up here by itself.")
            self._update_bar()
            return
        self.empty.set_visible(False)
        self.grid.set_visible(True)
        for v in views:
            card = GameCard(v, root, self.on_open, self._toggle, v.appid in self.selected)
            self.cards[v.appid] = card
            self.grid.append(card)
        needing = [v for v in views if v.status in ("ready", "new")]
        folders = plural(libraries, "Steam folder")
        if needing:
            self.subtitle.set_text(f"{plural(len(views), 'game')} in {folders}, {len(needing)} can be improved")
        else:
            self.subtitle.set_text(f"{plural(len(views), 'game')} in {folders}, all up to date")
        self.select_needed.set_visible(bool(needing))
        self._update_bar()

    def _toggle(self, appid: int, on: bool) -> None:
        if on:
            self.selected.add(appid)
        else:
            self.selected.discard(appid)
        self._update_bar()

    def set_selection(self, appids: set[int]) -> None:
        self.selected = set(appids)
        for appid, card in self.cards.items():
            card.check.set_active(appid in self.selected)
        self._update_bar()

    def select_where_needed(self) -> None:
        self.set_selection({v.appid for v in self.views if v.status in ("ready", "new")})

    def _update_bar(self) -> None:
        n = len(self.selected)
        self.count.set_text(f"{plural(n, 'game')} selected")
        self.bar.set_reveal_child(n > 0)
