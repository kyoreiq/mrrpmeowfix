from __future__ import annotations

import time
from typing import Callable

from gi.repository import Adw, Gio, Gtk

from ..core import GameView
from ..rules import GE_DOWNLOAD
from . import art
from .util import FixedPicture, esc, hbox, label, plural, tier_pill, vbox

KIND_NAMES = {"launch": "Launch option", "proton": "Proton version", "verb": "Windows component"}


def _code(text: str) -> Gtk.Label:
    lab = label(text, "code", ellipsize=True)
    lab.set_width_chars(min(len(text), 18))
    lab.set_max_width_chars(30)
    lab.set_tooltip_text(text)
    lab.set_valign(Gtk.Align.CENTER)
    return lab


def _cmdbox(title: str, text: str) -> Gtk.Box:
    box = vbox(0)
    box.append(label(title, "cmd-label"))
    inner = vbox(0, "cmdbox")
    inner.append(label(text or "(empty)", "mono", wrap=True, selectable=True,
                       *([] if text else ["faint"])))
    box.append(inner)
    return box


class GamePage(Adw.NavigationPage):
    def __init__(self, view: GameView, root, after_launch: str,
                 on_apply: Callable[[list[int]], None], on_undo: Callable[[int], None]):
        super().__init__(title=view.name, tag=f"game-{view.appid}")
        self.view = view
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar(show_title=False, show_start_title_buttons=False))

        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        clamp = Adw.Clamp(maximum_size=880, tightening_threshold=600)
        body = vbox(18)
        body.set_margin_start(28)
        body.set_margin_end(28)
        body.set_margin_bottom(40)

        # Hero art with the title on top
        hero = Gtk.Overlay()
        hero.add_css_class("hero")
        hero.set_overflow(Gtk.Overflow.HIDDEN)
        hero.set_size_request(-1, 250)
        self.hero_pic = FixedPicture(0, 250, hexpand=True)
        hero.set_child(self.hero_pic)
        scrim = Gtk.Box()
        scrim.add_css_class("hero-scrim")
        hero.add_overlay(scrim)
        title = label(view.name, "hero-title", wrap=True)
        title.set_valign(Gtk.Align.END)
        title.set_halign(Gtk.Align.START)
        hero.add_overlay(title)
        body.append(hero)
        art.load(root, view.appid, ["library_hero", "header"], 1760, 620, self._hero)

        chips = hbox(8)
        tp = tier_pill(view.tier)
        tp.set_margin_start(0)
        tp.set_margin_top(0)
        tp.set_margin_bottom(0)
        chips.append(tp)
        if view.native:
            chips.append(label("Runs on Linux natively", "chip", "accent"))
        elif view.proton_now:
            chips.append(label(f"Proton: {view.proton_now}", "chip"))
        else:
            chips.append(label("Proton: Steam default", "chip"))
        for ac in view.anticheat:
            chips.append(label(ac, "chip", "warn"))
        if view.plan.good_reports:
            who = {"nvidia": "NVIDIA ", "amd": "AMD ", "intel": "Intel "}.get(view.plan.bucket or "", "")
            chips.append(label(f"Based on {view.plan.good_reports} {who}reports where it worked", "chip"))
        body.append(chips)

        for note in view.plan.notes:
            body.append(label(note, "muted", wrap=True))

        # Actions
        actions = hbox(10)
        if view.installed:
            apply_btn = Gtk.Button(label="Apply fixes" if view.pending else "Up to date")
            apply_btn.add_css_class("pill-accent")
            apply_btn.set_sensitive(view.pending > 0)
            apply_btn.connect("clicked", lambda *_: on_apply([view.appid]))
            actions.append(apply_btn)
            if view.entry:
                undo = Gtk.Button(label="Undo fixes")
                undo.add_css_class("quiet")
                undo.connect("clicked", lambda *_: on_undo(view.appid))
                actions.append(undo)
        else:
            actions.append(label("Not installed. Install it in Steam and these fixes can be applied.", "muted", wrap=True))
        pdb = Gtk.Button(label="Open on ProtonDB")
        pdb.add_css_class("flat")
        pdb.connect("clicked", lambda *_: Gtk.UriLauncher(uri=f"https://www.protondb.com/app/{view.appid}").launch(
            self.get_root(), None, None, None))
        actions.append(pdb)
        body.append(actions)

        # The fix list
        body.append(label("What mrrpmeowfix changes", "section-title"))
        items = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        items.add_css_class("boxed-list")
        if not view.plan.items:
            row = Adw.ActionRow(title="Nothing for this game", subtitle="There are no tweaks that fit your PC.")
            items.append(row)
        for item in view.plan.items:
            subtitle = item.about
            if item.evidence:
                subtitle += "\n" + item.evidence
            if item.blocked:
                subtitle += "\n" + item.blocked
            row = Adw.ActionRow(title=esc(item.label), subtitle=esc(subtitle))
            row.set_subtitle_lines(0)
            row.set_tooltip_text(KIND_NAMES.get(item.kind, ""))
            if item.risky:
                tag = label("Risky", "risky-tag")
                tag.set_valign(Gtk.Align.CENTER)
                row.add_suffix(tag)
            value = "GE-Proton (downloads first)" if item.value == GE_DOWNLOAD else item.value
            row.add_suffix(_code(value))
            if item.blocked:
                row.add_css_class("blocked")
                icon = Gtk.Image(icon_name="changes-prevent-symbolic", tooltip_text=item.blocked)
            else:
                icon = Gtk.Image(icon_name="object-select-symbolic", tooltip_text="Will be applied")
                icon.add_css_class("check-ok")
            row.add_suffix(icon)
            items.append(row)
        body.append(items)

        if view.installed:
            body.append(label("Launch options", "section-title"))
            body.append(_cmdbox("Now", view.launch_now))
            if after_launch != view.launch_now:
                body.append(_cmdbox("After applying", after_launch))

        last = view.entry.get("last_result") if view.entry else None
        if last:
            when = time.strftime("%-d %b %Y, %H:%M", time.localtime(last.get("at", 0)))
            body.append(label(f"Last applied {when}", "section-title"))
            changes = last.get("added", []) + last.get("removed", [])
            summary = (plural(len(last.get("added", [])), "change") + " added, "
                       + plural(len(last.get("removed", [])), "change") + " removed")
            body.append(label(summary if changes else "Nothing changed that time.", "muted"))

        clamp.set_child(body)
        scroller.set_child(clamp)
        toolbar.set_content(scroller)
        self.set_child(toolbar)

    def _hero(self, texture) -> None:
        if texture is not None:
            self.hero_pic.set_paintable(texture)


def open_uri(widget: Gtk.Widget, uri: str) -> None:
    Gtk.UriLauncher(uri=uri).launch(widget.get_root(), None, None, None)


def open_folder(widget: Gtk.Widget, path) -> None:
    Gtk.FileLauncher(file=Gio.File.new_for_path(str(path))).launch(widget.get_root(), None, None, None)
