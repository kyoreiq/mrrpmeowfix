from __future__ import annotations

from typing import Callable

from gi.repository import Adw, Gtk

from .. import VERSION, fixlist, paths, updater
from ..core import Service
from . import dialogs
from .gamepage import open_folder
from .util import esc, label, page_head, vbox


class SettingsPage(Adw.NavigationPage):
    def __init__(self, service: Service, on_changed: Callable[[str], None], on_update_data: Callable[[], None],
                 on_check_update: Callable[[], None], on_refresh_fixlist: Callable[[], None]):
        super().__init__(title="Settings", tag="settings")
        self.service = service
        self.on_changed = on_changed
        self._quiet = False

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar(show_title=False, show_start_title_buttons=False))
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        clamp = Adw.Clamp(maximum_size=760)
        body = vbox(22)
        body.set_margin_start(28)
        body.set_margin_end(28)
        body.set_margin_bottom(40)
        head, _ = page_head("Settings", "Changes here apply the next time you press Apply fixes.")
        body.append(head)
        s = service.settings

        fixes = Adw.PreferencesGroup(title="Fixes")
        self.risky = Adw.SwitchRow(
            title="Risky fixes",
            subtitle="Proton switches on anti-cheat games, Windows components and experimental options. Off by default.")
        self.risky.set_active(s.risky)
        self.risky.connect("notify::active", self._risky_toggled)
        fixes.add(self.risky)
        overlay = Adw.SwitchRow(title="FPS overlay",
                                subtitle="Adds MangoHud to games so FPS and frame times show in a corner.")
        overlay.set_active(s.overlay)
        overlay.connect("notify::active", lambda r, _p: self._set("overlay", r.get_active()))
        fixes.add(overlay)
        confirm = Adw.SwitchRow(title="Ask before applying",
                                subtitle="Shows the list of changes first. Steam is always closed and reopened for you.")
        confirm.set_active(s.confirm_apply)
        confirm.connect("notify::active", lambda r, _p: self._set("confirm_apply", r.get_active()))
        self.confirm = confirm
        fixes.add(confirm)
        body.append(fixes)

        steam_group = Adw.PreferencesGroup(title="Steam")
        accounts = service.accounts
        if accounts:
            model = Gtk.StringList.new([a.name for a in accounts])
            row = Adw.ComboRow(title="Steam account", subtitle="Launch options are saved per account.", model=model)
            current = next((i for i, a in enumerate(accounts) if service.account and a.account_id == service.account.account_id), 0)
            row.set_selected(current)
            row.connect("notify::selected", lambda r, _p: self._account(accounts[r.get_selected()].account_id))
            steam_group.add(row)
        where = Adw.ActionRow(title="Steam folder",
                              subtitle=esc(str(service.root.path) if service.root else "Steam wasn't found"))
        steam_group.add(where)
        body.append(steam_group)

        data = Adw.PreferencesGroup(title="Fix data")
        auto = Adw.SwitchRow(title="Update fix data by itself",
                             subtitle="Checks for ProtonDB's monthly report data about once a week.")
        auto.set_active(s.auto_update_data)
        auto.connect("notify::active", lambda r, _p: self._set("auto_update_data", r.get_active()))
        data.add(auto)
        self.data_row = Adw.ActionRow(title="Update now")
        self.update_btn = Gtk.Button(label="Update", valign=Gtk.Align.CENTER)
        self.update_btn.connect("clicked", lambda *_: on_update_data())
        self.data_row.add_suffix(self.update_btn)
        data.add(self.data_row)
        self.refresh_data_row()
        body.append(data)

        updates = Adw.PreferencesGroup(title="Updates")
        auto_app = Adw.SwitchRow(title="Update the app by itself",
                                 subtitle="New versions download in the background and start after a restart.")
        auto_app.set_active(s.auto_update_app)
        auto_app.connect("notify::active", lambda r, _p: self._set("auto_update_app", r.get_active()))
        updates.add(auto_app)
        self.update_row = Adw.ActionRow(title="Check for updates")
        self.update_check = Gtk.Button(label="Check", valign=Gtk.Align.CENTER)
        self.update_check.connect("clicked", lambda *_: on_check_update())
        self.update_row.add_suffix(self.update_check)
        updates.add(self.update_row)
        self.fixlist_row = Adw.ActionRow(title="Fix list")
        self.fixlist_btn = Gtk.Button(label="Refresh", valign=Gtk.Align.CENTER)
        self.fixlist_btn.connect("clicked", lambda *_: on_refresh_fixlist())
        self.fixlist_row.add_suffix(self.fixlist_btn)
        updates.add(self.fixlist_row)
        self.set_update_status()
        self.set_fixlist_status()
        # Without an update source there's nothing to show here.
        updates.set_visible(bool(fixlist.raw_url(fixlist.source())))
        body.append(updates)

        files = Adw.PreferencesGroup(title="Backups")
        backups = Adw.ActionRow(title="Open backups folder",
                                subtitle="A copy of Steam's settings is saved before every change. The last 10 are kept.",
                                activatable=True)
        backups.add_suffix(Gtk.Image(icon_name="folder-open-symbolic"))
        backups.connect("activated", lambda *_: self._open_backups())
        files.add(backups)
        body.append(files)

        body.append(label(f"mrrpmeowfix {VERSION}. Fix data comes from ProtonDB's public reports and "
                          "AreWeAntiCheatYet.", "faint", wrap=True))

        clamp.set_child(body)
        scroller.set_child(clamp)
        toolbar.set_content(scroller)
        self.set_child(toolbar)

    def refresh_data_row(self, busy: str | None = None) -> None:
        idx = self.service.index
        if busy:
            self.data_row.set_subtitle(busy)
            self.update_btn.set_sensitive(False)
        else:
            self.data_row.set_subtitle(f"Using reports from {idx.describe_source()}, {len(idx.games):,} games.")
            self.update_btn.set_sensitive(True)

    def set_update_status(self, text: str | None = None) -> None:
        src = fixlist.source()
        if not updater.is_installed_copy():
            self.update_row.set_subtitle("Off: this copy runs from a folder. Install it with install.sh to get updates.")
            self.update_check.set_sensitive(False)
            return
        if not fixlist.raw_url(src):
            self.update_row.set_subtitle(f"You have version {VERSION}. No GitHub repo is set up for updates yet.")
            self.update_check.set_sensitive(False)
            return
        self.update_row.set_subtitle(text or f"You have version {VERSION}.")
        self.update_check.set_sensitive(text is None or not text.endswith("…"))

    def set_fixlist_status(self, busy: bool = False) -> None:
        fl = fixlist.load()
        src = fixlist.source()
        games = f"{len(fl)} game{'s' if len(fl) != 1 else ''}"
        if not fixlist.raw_url(src):
            self.fixlist_row.set_subtitle(f"Built-in list, {games}. No GitHub repo is set up yet.")
            self.fixlist_btn.set_sensitive(False)
            return
        when = f", updated {fl.updated}" if fl.updated else ""
        self.fixlist_row.set_subtitle("Getting the newest fix list…" if busy else f"{games} from {src['repo']}{when}.")
        self.fixlist_btn.set_sensitive(not busy)

    def _set(self, key: str, value) -> None:
        self.service.with_settings(**{key: value})
        self.on_changed(key)

    def _account(self, account_id: int) -> None:
        self.service.set_account(account_id)
        self.on_changed("account")

    def _open_backups(self) -> None:
        folder = paths.data_dir() / "backups"
        folder.mkdir(parents=True, exist_ok=True)
        open_folder(self, folder)

    def _risky_toggled(self, row: Adw.SwitchRow, _pspec) -> None:
        if self._quiet:
            return
        if not row.get_active():
            self._set("risky", False)
            return

        def yes():
            self._set("risky", True)

        def no():
            self._quiet = True
            row.set_active(False)
            self._quiet = False

        dialogs.risky_confirm(self, yes, no)

    def set_confirm(self, value: bool) -> None:
        self.confirm.set_active(value)
