from __future__ import annotations

from typing import Callable

from gi.repository import Adw, GLib, Gtk

from ..apply import GameResult
from .util import hbox, label, plural, vbox

RISKY_SECONDS = 5

RISKY_INTRO = "Risky fixes are changes some players needed, but they can also make things worse."
RISKY_BODY = (
    "With this on, mrrpmeowfix may:\n"
    "•  Switch the Proton version on games with anti-cheat. That can stop online play, "
    "and in rare cases anti-cheat can flag it.\n"
    "•  Install Windows components (like Visual C++ runtimes) into a game's Proton files. "
    "These can't be removed again without resetting that game's Proton files.\n"
    "•  Turn on experimental options that fix one game and crash another, or lower FPS.\n\n"
    "Turn it off again any time. The next Apply removes the risky fixes it added and keeps the normal ones."
)


def _wide(dialog: Adw.AlertDialog) -> None:
    if hasattr(dialog, "set_prefer_wide_layout"):
        dialog.set_prefer_wide_layout(True)


def risky_confirm(parent: Gtk.Widget, on_yes: Callable[[], None], on_no: Callable[[], None]) -> None:
    dialog = Adw.AlertDialog(heading="ARE YOU SURE?", body=RISKY_INTRO)
    _wide(dialog)
    details = label(RISKY_BODY, wrap=True)
    details.set_max_width_chars(52)
    dialog.set_extra_child(details)
    dialog.add_response("cancel", "Keep it off")
    dialog.add_response("enable", f"Yes, turn on ({RISKY_SECONDS})")
    dialog.set_response_appearance("enable", Adw.ResponseAppearance.DESTRUCTIVE)
    dialog.set_response_enabled("enable", False)
    dialog.set_default_response("cancel")
    dialog.set_close_response("cancel")
    left = [RISKY_SECONDS]

    def tick() -> bool:
        left[0] -= 1
        if left[0] > 0:
            dialog.set_response_label("enable", f"Yes, turn on ({left[0]})")
            return True
        dialog.set_response_label("enable", "Yes, turn on")
        dialog.set_response_enabled("enable", True)
        return False

    timer = GLib.timeout_add_seconds(1, tick)

    def response(_d, rid: str) -> None:
        if left[0] > 0:
            GLib.source_remove(timer)
        (on_yes if rid == "enable" else on_no)()

    dialog.connect("response", response)
    dialog.present(parent)


def _change_lines(res: GameResult, box: Gtk.Box) -> None:
    for text in res.added:
        box.append(label(f"+  {text}", "res-add", wrap=True))
    for text in res.removed:
        box.append(label(f"−  {text}", "res-remove", wrap=True))
    for text in res.skipped:
        box.append(label(f"·  {text}", "res-skip", wrap=True))
    for text in res.errors:
        box.append(label(f"!  {text}", "res-error", wrap=True))


def confirm_apply(parent: Gtk.Widget, names: dict[int, str], previews: list[GameResult], steam_running: bool,
                  ge_download: bool, on_confirm: Callable[[bool], None]) -> None:
    changing = [p for p in previews if p.changed]
    n = len(changing) or len(previews)
    dialog = Adw.AlertDialog(heading=f"Apply fixes to {plural(n, 'game')}?")
    _wide(dialog)
    body = []
    if steam_running:
        body.append("Steam will close for a moment while the changes are saved, then open again.")
    if ge_download:
        body.append("GE-Proton gets downloaded first (around 450 MB).")
    body.append("Everything is backed up and each game can be undone.")
    dialog.set_body(" ".join(body))

    content = vbox(6)
    for p in previews:
        if not p.changed and not p.skipped:
            continue
        content.append(label(names.get(p.appid, str(p.appid)), "result-game"))
        _change_lines(p, content)
    if not changing and ge_download:
        content.append(label("The Proton version changes once GE-Proton is installed.", "muted", wrap=True))
    dont_ask = Gtk.CheckButton(label="Don't show this before applying again")
    dont_ask.set_margin_top(10)
    content.append(dont_ask)
    content.set_size_request(440, -1)
    scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True,
                                  max_content_height=380)
    scroller.set_child(content)
    dialog.set_extra_child(scroller)

    dialog.add_response("cancel", "Cancel")
    dialog.add_response("apply", "Apply fixes")
    dialog.set_response_appearance("apply", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("apply")
    dialog.set_close_response("cancel")
    dialog.connect("response", lambda _d, rid: rid == "apply" and on_confirm(dont_ask.get_active()))
    dialog.present(parent)
    GLib.idle_add(lambda: scroller.get_vadjustment().set_value(0) and False)


class ProgressDialog(Adw.Dialog):
    def __init__(self, title: str):
        super().__init__(title=title, can_close=False, content_width=420)
        box = vbox(14)
        box.set_margin_start(28)
        box.set_margin_end(28)
        box.set_margin_top(30)
        box.set_margin_bottom(30)
        self.text = label("Starting", wrap=True)
        box.append(label(title, "section-title"))
        box.append(self.text)
        self.bar = Gtk.ProgressBar()
        box.append(self.bar)
        self.set_child(box)
        self._pulse = GLib.timeout_add(120, self._tick)
        self._fraction = None

    def _tick(self) -> bool:
        if self._fraction is None:
            self.bar.pulse()
        return True

    def update(self, fraction: float, text: str) -> None:
        self._fraction = fraction
        self.bar.set_fraction(max(0.0, min(1.0, fraction)))
        self.text.set_text(text)

    def finish(self) -> None:
        GLib.source_remove(self._pulse)
        self.set_can_close(True)
        self.close()


def results_dialog(parent: Gtk.Widget, title: str, names: dict[int, str], results: list[GameResult],
                   on_undo: Callable[[int], None] | None) -> None:
    dialog = Adw.Dialog(title=title, content_width=560, content_height=560)
    toolbar = Adw.ToolbarView()
    toolbar.add_top_bar(Adw.HeaderBar())
    scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
    box = vbox(8)
    box.set_margin_start(24)
    box.set_margin_end(24)
    box.set_margin_bottom(24)

    changed = sum(1 for r in results if r.changed)
    errors = sum(1 for r in results if r.errors)
    summary = f"Changed {plural(changed, 'game')}."
    if errors:
        summary += f" {plural(errors, 'game')} had a problem, see below."
    box.append(label(summary, "page-sub", wrap=True))

    for res in results:
        head = hbox(8)
        name = label(names.get(res.appid, str(res.appid)), "result-game", ellipsize=True)
        name.set_hexpand(True)
        head.append(name)
        if on_undo and res.changed:
            undo = Gtk.Button(label="Undo", valign=Gtk.Align.CENTER)
            undo.add_css_class("flat")
            undo.connect("clicked", lambda _b, a=res.appid: (dialog.close(), on_undo(a)))
            head.append(undo)
        box.append(head)
        if not (res.added or res.removed or res.skipped or res.errors):
            box.append(label("Nothing needed changing.", "res-skip"))
        _change_lines(res, box)
        for note in res.notes:
            box.append(label(note, "faint", wrap=True))

    scroller.set_child(box)
    toolbar.set_content(scroller)
    close = Gtk.Button(label="Done", halign=Gtk.Align.END)
    close.add_css_class("pill-accent")
    close.set_margin_end(20)
    close.set_margin_bottom(16)
    close.set_margin_top(8)
    close.connect("clicked", lambda *_: dialog.close())
    toolbar.add_bottom_bar(close)
    dialog.set_child(toolbar)
    dialog.present(parent)
