from __future__ import annotations

import subprocess
from typing import Callable

from gi.repository import Adw, Gdk, Gtk

from .. import system
from ..system import Check, SystemInfo
from .util import clear, hbox, label, page_head, vbox

ICONS = {True: ("object-select-symbolic", "check-ok"), False: ("dialog-warning-symbolic", "check-bad"),
         None: ("dialog-information-symbolic", "check-info")}


class PcPage(Adw.NavigationPage):
    def __init__(self, on_recheck: Callable[[], None], on_install_ge: Callable[[Callable], None]):
        super().__init__(title="Your PC", tag="pc")
        self.on_install_ge = on_install_ge
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar(show_title=False, show_start_title_buttons=False)
        again = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Check again")
        again.connect("clicked", lambda *_: on_recheck())
        header.pack_end(again)
        toolbar.add_top_bar(header)

        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        clamp = Adw.Clamp(maximum_size=860)
        body = vbox(18)
        body.set_margin_start(28)
        body.set_margin_end(28)
        body.set_margin_bottom(40)
        head, self.subtitle = page_head("Your PC", "")
        body.append(head)
        self.specs = Gtk.Grid(column_spacing=28, row_spacing=8)
        body.append(self.specs)
        body.append(label("Checks", "section-title"))
        self.list = vbox(10)
        body.append(self.list)
        clamp.set_child(body)
        scroller.set_child(clamp)
        toolbar.set_content(scroller)
        self.set_child(toolbar)

    def set_info(self, info: SystemInfo, checks: list[Check]) -> None:
        bad = [c for c in checks if c.ok is False]
        self.subtitle.set_text("Everything games need is in place." if not bad else
                               f"{len(bad)} thing{'s' if len(bad) != 1 else ''} worth fixing. "
                               "Each one has the command to run.")
        clear(self.specs)
        gpu = system.GPU_NAMES[info.gpu] + (f" {info.gpu_name}" if info.gpu_name else "")
        if info.driver:
            gpu += f", driver {info.driver}"
        rows = [
            ("System", info.distro),
            ("Kernel", info.kernel),
            ("Processor", info.cpu or "Unknown"),
            ("Graphics", gpu),
            ("Memory", f"{info.ram_gb} GB" if info.ram_gb else "Unknown"),
            ("Desktop", " on ".join(x for x in (info.desktop, info.session.capitalize()) if x) or "Unknown"),
        ]
        for i, (k, v) in enumerate(rows):
            self.specs.attach(label(k, "spec-key"), 0, i, 1, 1)
            self.specs.attach(label(v, "spec-value", wrap=True), 1, i, 1, 1)

        clear(self.list)
        for check in sorted(checks, key=lambda c: {False: 0, None: 2, True: 1}[c.ok]):
            self.list.append(self._card(check))

    def _card(self, check: Check) -> Gtk.Widget:
        card = vbox(8, "check-card")
        top = hbox(12)
        icon_name, css = ICONS[check.ok]
        icon = Gtk.Image(icon_name=icon_name)
        icon.add_css_class(css)
        icon.set_valign(Gtk.Align.START)
        icon.set_margin_top(2)
        top.append(icon)
        text = vbox(2)
        text.set_hexpand(True)
        text.append(label(check.title, "game-title"))
        text.append(label(check.detail, "muted", wrap=True))
        top.append(text)
        card.append(top)

        if check.command:
            row = hbox(8)
            row.set_margin_start(28)
            box = vbox(0, "cmdbox")
            box.set_hexpand(True)
            box.append(label(check.command, "mono", wrap=True, selectable=True))
            row.append(box)
            copy = Gtk.Button(icon_name="edit-copy-symbolic", tooltip_text="Copy command", valign=Gtk.Align.CENTER)
            copy.connect("clicked", lambda *_: self._copy(check.command))
            row.append(copy)
            term = system.terminal_command(check.command)
            if term and not check.command.startswith("Add "):
                run = Gtk.Button(icon_name="utilities-terminal-symbolic", tooltip_text="Open a terminal and run it",
                                 valign=Gtk.Align.CENTER)
                run.connect("clicked", lambda *_: subprocess.Popen(term, start_new_session=True))
                row.append(run)
            card.append(row)

        if check.action == "install-ge":
            row = hbox(12)
            row.set_margin_start(28)
            btn = Gtk.Button(label="Install the newest GE-Proton")
            btn.add_css_class("pill-accent")
            bar = Gtk.ProgressBar(show_text=True, valign=Gtk.Align.CENTER, hexpand=True)
            bar.set_visible(False)

            def progress(frac: float, text: str) -> None:
                bar.set_visible(True)
                bar.set_fraction(max(0.0, min(1.0, frac)))
                bar.set_text(text)

            def start(*_):
                btn.set_sensitive(False)
                self.on_install_ge(progress)

            btn.connect("clicked", start)
            row.append(btn)
            row.append(bar)
            card.append(row)
        return card

    def _copy(self, text: str) -> None:
        Gdk.Display.get_default().get_clipboard().set(text)
        root = self.get_root()
        if hasattr(root, "toast"):
            root.toast("Command copied")
