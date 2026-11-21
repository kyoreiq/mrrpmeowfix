from __future__ import annotations

import time

from gi.repository import Adw, Gio, GLib, Gtk

from .. import VERSION, anticheat, apply, fixlist, index, protonge, steam, system, updater
from ..core import GameView, Service
from ..index import GameStats
from . import dialogs
from .gamepage import GamePage
from .library import LibraryPage
from .pcpage import PcPage
from .search import SearchPage
from .settingspage import SettingsPage
from .util import hbox, label, on_main, plural, run_async, show_error, vbox

NAV = [
    ("library", "Library", "view-grid-symbolic"),
    ("search", "All games", "system-search-symbolic"),
    ("pc", "Your PC", "computer-symbolic"),
    ("settings", "Settings", "emblem-system-symbolic"),
]
DATA_CHECK_EVERY = 5 * 86400
WATCH_EVENTS = {
    Gio.FileMonitorEvent.CREATED, Gio.FileMonitorEvent.DELETED, Gio.FileMonitorEvent.MOVED_IN,
    Gio.FileMonitorEvent.MOVED_OUT, Gio.FileMonitorEvent.RENAMED,
}


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application, service: Service):
        super().__init__(application=app, title="mrrpmeowfix", default_width=1220, default_height=820)
        self.set_size_request(780, 540)
        self.service = service
        self.views: list[GameView] = []
        self.by_id: dict[int, GameView] = {}
        self.ge_latest: str | None = None
        self._monitors: list[Gio.FileMonitor] = []
        self._watched: list[str] = []
        self._refresh_timer = 0
        self._busy = False

        self._pending_release: updater.Release | None = None
        for name, handler in (("restart", lambda *_: updater.restart()),
                              ("update-app", lambda *_: self.update_app())):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            self.add_action(action)

        cleanup = Gio.SimpleAction.new("remove-risky", None)
        cleanup.connect("activate", lambda *_: self.start_apply(self.service.risky_games(self.views)))
        self.add_action(cleanup)

        self.toasts = Adw.ToastOverlay()
        root = hbox(0)

        side = Adw.ToolbarView()
        side.add_css_class("sidebar-pane")
        side.set_size_request(236, -1)
        side.add_top_bar(Adw.HeaderBar(show_end_title_buttons=False, show_title=False))
        sbox = vbox(0)
        mark = Gtk.Label(xalign=0)
        mark.set_markup('mrrpmeow<span foreground="#a9d1ff">fix</span>')
        mark.add_css_class("wordmark")
        mark.set_margin_start(22)
        mark.set_margin_bottom(22)
        sbox.append(mark)
        self.nav = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.nav.add_css_class("nav")
        for key, text, icon in NAV:
            row = Gtk.ListBoxRow()
            row.key = key
            inner = hbox(12)
            inner.append(Gtk.Image(icon_name=icon))
            inner.append(label(text))
            row.set_child(inner)
            self.nav.append(row)
        self.nav.connect("row-selected", self._nav_selected)
        sbox.append(self.nav)
        spacer = Gtk.Box(vexpand=True)
        sbox.append(spacer)
        self.data_note = label("", "data-note", wrap=True)
        sbox.append(self.data_note)
        side.set_content(sbox)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, hexpand=True)
        self.lib_nav = Adw.NavigationView()
        self.library = LibraryPage(self.open_game, self.start_apply, self.refresh)
        self.lib_nav.add(self.library)
        self.search_nav = Adw.NavigationView()
        self.search = SearchPage(service.search, lambda: set(self.by_id), self.open_search_result,
                                 len(service.index.games))
        self.search_nav.add(self.search)
        self.pc_nav = Adw.NavigationView()
        self.pc = PcPage(self.refresh_pc, self.install_ge)
        self.pc_nav.add(self.pc)
        self.settings_nav = Adw.NavigationView()
        self.settings_page = SettingsPage(service, self.settings_changed, lambda: self.update_data(silent=False),
                                          lambda: self.check_app_update(manual=True), self.refresh_fixlist)
        self.settings_nav.add(self.settings_page)
        for key, nav in (("library", self.lib_nav), ("search", self.search_nav),
                         ("pc", self.pc_nav), ("settings", self.settings_nav)):
            self.stack.add_named(nav, key)

        root.append(side)
        root.append(self.stack)
        self.toasts.set_child(root)
        self.set_content(self.toasts)
        self.nav.select_row(self.nav.get_row_at_index(0))

        self.refresh()
        self._update_data_note()
        self._after_update()
        self._background_start()

    # Navigation

    def _nav_selected(self, _lb, row) -> None:
        if row is None:
            return
        self.stack.set_visible_child_name(row.key)
        if row.key == "search":
            self.search.focus()

    def toast(self, text: str, button: str | None = None, action: str | None = None) -> None:
        t = Adw.Toast(title=text, timeout=6 if button else 3)
        if button and action:
            t.set_button_label(button)
            t.set_action_name(action)
        self.toasts.add_toast(t)

    def _update_data_note(self, busy: str | None = None) -> None:
        idx = self.service.index
        self.data_note.set_text(busy or f"Fix data from {idx.describe_source()} reports")

    # Scanning

    def refresh(self, *_args) -> None:
        self.service.reload_steam()
        if not self.service.root:
            self.library.show_message("Steam wasn't found",
                                      "Install Steam and log in once, then press the refresh button.")
            self.refresh_pc()
            return
        try:
            self.views = self.service.scan()
        except Exception as e:  # noqa: BLE001 - a broken Steam file shouldn't kill the window
            self.library.show_message("Couldn't read your Steam games", str(e))
            return
        self.by_id = {v.appid: v for v in self.views}
        self.library.set_views(self.views, self.service.root, len(self.service.libraries()))
        self._watch()
        self.refresh_pc()
        self._reopen_game_pages()

    def _reopen_game_pages(self) -> None:
        for nav, root_page in ((self.lib_nav, self.library), (self.search_nav, self.search)):
            page = nav.get_visible_page()
            if isinstance(page, GamePage):
                old = page.view
                view = self.by_id.get(old.appid) or self.service.view(old.appid, old.name, None)
                nav.replace([root_page, self._game_page(view)])

    def _schedule_refresh(self) -> None:
        if self._refresh_timer:
            GLib.source_remove(self._refresh_timer)

        def fire():
            self._refresh_timer = 0
            if self._busy or not self.service.root:
                return False
            # Steam rewrites manifests constantly while downloading; only rebuild when the game list changed.
            if {g.appid for g in steam.games(self.service.root)} != set(self.by_id):
                self.refresh()
            return False

        self._refresh_timer = GLib.timeout_add(2000, fire)

    def _watch(self) -> None:
        dirs = [str(lib / "steamapps") for lib in self.service.libraries()]
        if dirs == self._watched:
            return
        for m in self._monitors:
            m.cancel()
        self._monitors = []
        for d in dirs:
            try:
                mon = Gio.File.new_for_path(d).monitor_directory(Gio.FileMonitorFlags.WATCH_MOVES, None)
            except GLib.Error:
                continue
            mon.connect("changed", self._steamapps_changed)
            self._monitors.append(mon)
        self._watched = dirs

    def _steamapps_changed(self, _mon, file: Gio.File, _other, event) -> None:
        name = file.get_basename() or ""
        if event in WATCH_EVENTS and (name.startswith("appmanifest_") or name == "libraryfolders.vdf"):
            self._schedule_refresh()

    def refresh_pc(self) -> None:
        s = self.service.settings
        checks = system.checks(self.service.info, self.service.root, s.overlay, s.risky, self.ge_latest)
        self.pc.set_info(self.service.info, checks)

    # Game pages

    def _game_page(self, view: GameView) -> GamePage:
        return GamePage(view, self.service.root, self.service.preview_launch(view), self.start_apply, self.start_undo)

    def open_game(self, view: GameView) -> None:
        self.lib_nav.push(self._game_page(view))

    def open_search_result(self, stats: GameStats) -> None:
        view = self.by_id.get(stats.appid) or self.service.view(stats.appid, stats.title, None)
        self.search_nav.push(self._game_page(view))

    # Applying

    def start_apply(self, appids: list[int]) -> None:
        views = [self.by_id[a] for a in appids if a in self.by_id]
        if not views:
            return
        previews = self.service.preview(views)
        ge = self.service.needs_ge(views)
        if not any(p.changed for p in previews) and not ge:
            self.toast("Nothing to change. Those games already have their fixes.")
            return
        names = {v.appid: v.name for v in views}

        def go(dont_ask: bool = False) -> None:
            if dont_ask:
                self.service.with_settings(confirm_apply=False)
                self.settings_page.set_confirm(False)
            self._run(lambda progress: self.service.apply([v.appid for v in views], progress),
                      "Applying fixes", names, "Fixes applied", undo=True)

        if self.service.settings.confirm_apply:
            dialogs.confirm_apply(self, names, previews, steam.is_running(), ge, go)
        else:
            go()

    def start_undo(self, appid: int) -> None:
        view = self.by_id.get(appid)
        name = view.name if view else str(appid)
        dialog = Adw.AlertDialog(
            heading=f"Undo fixes for {name}?",
            body="Launch options and the Proton version go back to how they were before mrrpmeowfix changed them. "
                 "Anything you typed into the launch options yourself stays.")
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("undo", "Undo fixes")
        dialog.set_response_appearance("undo", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_close_response("cancel")
        dialog.connect("response", lambda _d, rid: rid == "undo" and self._run(
            lambda progress: [self.service.undo(appid, progress)], "Undoing fixes", {appid: name}, "Fixes undone",
            undo=False))
        dialog.present(self)

    def _run(self, work, title: str, names: dict[int, str], done_title: str, undo: bool) -> None:
        progress_dialog = dialogs.ProgressDialog(title)
        progress_dialog.present(self)
        self._busy = True

        def progress(frac: float, text: str) -> None:
            on_main(progress_dialog.update, frac, text)

        def done(results) -> None:
            self._busy = False
            progress_dialog.finish()
            self.refresh()
            dialogs.results_dialog(self, done_title, names, results, self.start_undo if undo else None)

        def failed(e: BaseException) -> None:
            self._busy = False
            progress_dialog.finish()
            self.refresh()
            if isinstance(e, apply.SteamRunning):
                show_error(self, "Steam is still open", "Steam didn't close in time, so nothing was changed. "
                           "Close Steam yourself (Steam menu, Exit) and try again.")
            else:
                show_error(self, "Something went wrong", f"Nothing more was changed. The error was: {e}")

        run_async(lambda: work(progress), done, failed)

    def install_ge(self, progress_cb) -> None:
        def progress(frac, text):
            on_main(progress_cb, frac, text)

        def done(name):
            self.toast(f"{name} installed. Steam shows it after a restart.")
            self.ge_latest = None
            self.refresh()

        def failed(e):
            show_error(self, "GE-Proton wasn't installed", str(e))
            self.refresh_pc()

        run_async(lambda: self.service.install_ge(progress), done, failed)

    # Settings and background work

    def settings_changed(self, key: str) -> None:
        if key in ("risky", "overlay", "account"):
            self.refresh()
        if key == "risky":
            if self.service.settings.risky:
                self.toast("Risky fixes are on. Games with risky fixes now list them as ready.")
            else:
                risky = self.service.risky_games(self.views)
                if risky:
                    self.toast(f"Risky fixes are off. {plural(len(risky), 'game')} still "
                               f"{'has' if len(risky) == 1 else 'have'} some applied.",
                               "Remove them now", "win.remove-risky")
                else:
                    self.toast("Risky fixes are off.")

    def update_data(self, silent: bool) -> None:
        self.settings_page.refresh_data_row("Checking for newer report data")
        self._update_data_note("Checking for newer fix data")

        def progress(_frac, text):
            on_main(self.settings_page.refresh_data_row, text)
            on_main(self._update_data_note, text)

        def done(changed: bool) -> None:
            self.service.with_settings(last_data_check=int(time.time()))
            if changed:
                self.service.reload_index()
                self.search.set_total(len(self.service.index.games))
                self.refresh()
                self.toast(f"Fix data updated to {self.service.index.describe_source()} reports")
            elif not silent:
                self.toast("Fix data is already the newest")
            self.settings_page.refresh_data_row()
            self._update_data_note()

        def failed(e) -> None:
            self.settings_page.refresh_data_row()
            self._update_data_note()
            if not silent:
                self.toast(f"Couldn't update fix data: {e}")

        run_async(lambda: index.refresh(progress, current_source=self.service.index.source), done, failed)

    def _background_start(self) -> None:
        appids = [v.appid for v in self.views]

        def work():
            try:
                anticheat.refresh()
            except Exception:  # noqa: BLE001 - offline is fine, the bundled list is used
                pass
            try:
                fixlist.refresh()
            except Exception:  # noqa: BLE001 - the cached or built-in list is used
                pass
            self.service.fetch_online(appids)
            try:
                return protonge.latest().tag
            except Exception:  # noqa: BLE001
                return None

        def done(ge_tag):
            self.ge_latest = ge_tag
            self.settings_page.set_fixlist_status()
            if not self._busy:
                self.refresh()

        run_async(work, done)
        s = self.service.settings
        if s.auto_update_data and time.time() - s.last_data_check > DATA_CHECK_EVERY:
            GLib.timeout_add_seconds(4, lambda: self.update_data(silent=True) and False)
        GLib.timeout_add_seconds(8, lambda: self.check_app_update(manual=False) and False)

    # App updates and the fix list

    def _after_update(self) -> None:
        s = self.service.settings
        if updater.is_installed_copy():
            if s.last_version and s.last_version != VERSION:
                try:
                    updater.refresh_desktop_files()
                except OSError:
                    pass
                self.toast(f"mrrpmeowfix updated to {VERSION}")
            updater.cleanup_old()
        if s.last_version != VERSION:
            self.service.with_settings(last_version=VERSION)

    def check_app_update(self, manual: bool) -> None:
        s = self.service.settings
        if not updater.is_installed_copy() or not fixlist.raw_url(fixlist.source()):
            return
        if not manual and time.time() - s.last_update_check < updater.CHECK_EVERY:
            return
        self.settings_page.set_update_status("Checking for updates…")

        def done(rel) -> None:
            self.service.with_settings(last_update_check=int(time.time()))
            if rel is None or not updater.newer(rel.version, VERSION):
                self.settings_page.set_update_status(f"You have the newest version ({VERSION}).")
                if manual:
                    self.toast("You have the newest version")
                return
            self._pending_release = rel
            if s.auto_update_app:
                self.update_app()
            else:
                self.settings_page.set_update_status(f"Version {rel.version} is out.")
                self.toast(f"mrrpmeowfix {rel.version} is out", "Update", "win.update-app")

        def failed(e) -> None:
            self.settings_page.set_update_status()
            if manual:
                self.toast(f"Couldn't check for updates: {e}")

        run_async(updater.latest, done, failed)

    def update_app(self) -> None:
        rel = self._pending_release
        if rel is None:
            self.check_app_update(manual=True)
            return
        self.settings_page.set_update_status(f"Installing version {rel.version}…")

        def done(version: str) -> None:
            self._pending_release = None
            self.settings_page.set_update_status(f"Version {version} is installed. Restart to use it.")
            self.toast(f"Updated to {version}. Restart to use it.", "Restart", "win.restart")

        def failed(e) -> None:
            self.settings_page.set_update_status()
            show_error(self, "The update wasn't installed", f"Your current version keeps working. {e}")

        run_async(lambda: updater.install(rel), done, failed)

    def refresh_fixlist(self) -> None:
        self.settings_page.set_fixlist_status(busy=True)

        def done(changed: bool) -> None:
            self.settings_page.set_fixlist_status()
            if changed:
                self.refresh()
                self.toast("Fix list updated")
            else:
                self.toast("The fix list hasn't changed")

        def failed(e) -> None:
            self.settings_page.set_fixlist_status()
            self.toast(f"Couldn't get the fix list: {e}")

        run_async(lambda: fixlist.refresh(force=True), done, failed)
