"""Everything the window needs, without any GTK: scanning, plans, applying."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import anticheat, apply, fixlist, index, launchopts, online, protonge, rules, steam, system, vdf
from .index import GameStats
from .rules import GE_DOWNLOAD, Plan
from .settings import Settings

Progress = Callable[[float, str], None]


@dataclass
class GameView:
    appid: int
    name: str
    game: steam.Game | None
    stats: GameStats | None
    native: bool
    anticheat: list[str]
    plan: Plan
    status: str
    pending: int
    entry: dict
    launch_now: str
    proton_now: str | None

    @property
    def installed(self) -> bool:
        return self.game is not None

    @property
    def tier(self) -> str | None:
        if self.native:
            return "native"
        live = online.cached_tier(self.appid)
        if live:
            return live
        return self.stats.rough_tier() if self.stats else None

    @property
    def risky_applied(self) -> bool:
        return bool(self.entry.get("risky"))


class SteamMissing(RuntimeError):
    pass


class Service:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings.load()
        self.index = index.load()
        self.ledger = apply.Ledger()
        self.info = system.detect()
        self.root: steam.SteamRoot | None = None
        self.account: steam.Account | None = None
        self.accounts: list[steam.Account] = []
        self.tools: set[str] = set()
        self.compat: list[steam.CompatTool] = []
        self.reload_steam()

    # Steam state

    def reload_steam(self) -> None:
        roots = steam.find_roots()
        self.root = roots[0] if roots else None
        self.accounts = steam.accounts(self.root) if self.root else []
        wanted = self.settings.account_id
        self.account = next((a for a in self.accounts if a.account_id == wanted), None) or (
            self.accounts[0] if self.accounts else None)
        self.tools = system.tools_available()
        self.compat = steam.compat_tools(self.root) if self.root else []

    def reload_index(self) -> None:
        self.index = index.load()

    def libraries(self) -> list[Path]:
        return steam.libraries(self.root) if self.root else []

    def _launch_options(self) -> dict[str, str]:
        if not self.account or not self.account.localconfig.exists():
            return {}
        data = vdf.loads(self.account.localconfig.read_text(encoding="utf-8", errors="replace"))
        apps = vdf.find(data, *apply.APPS_PATH) or {}
        return {k: v.get("LaunchOptions", "") for k, v in apps.items() if isinstance(v, dict)}

    # Plans

    def context(self, appid: int, mapping: dict[str, str]) -> rules.Context:
        entry = self.ledger.get(self.account, appid) if self.account else {}
        return rules.Context(
            gpu=self.info.gpu if self.info.gpu != "unknown" else "all",
            hybrid=self.info.hybrid,
            risky_on=self.settings.risky,
            overlay_on=self.settings.overlay,
            tools=self.tools,
            compat_tools=self.compat,
            mapping=mapping,
            ours=entry,
        )

    def is_native(self, appid: int, stats: GameStats | None, mapping: dict[str, str]) -> bool:
        if str(appid) in mapping:
            return False
        linux = online.cached_linux(appid)
        if linux is not None:
            return linux
        if stats:
            b = stats.buckets.get("all") or {}
            good = b.get("g", 0)
            return bool(good) and b.get("v", {}).get("native", 0) / good >= 0.5
        return False

    def view(self, appid: int, name: str, game: steam.Game | None = None,
             mapping: dict[str, str] | None = None, launch: dict[str, str] | None = None,
             with_status: bool = True) -> GameView:
        mapping = steam.compat_mapping(self.root) if mapping is None and self.root else (mapping or {})
        launch = self._launch_options() if launch is None else launch
        stats = self.index.get(appid)
        native = self.is_native(appid, stats, mapping)
        ac = anticheat.load().check(appid, name, game.installdir if game else Path("/nonexistent"))
        plan = rules.build_plan(appid, stats, self.context(appid, mapping), native=native, anticheat=ac,
                                fixlist=fixlist.load().get(appid))
        entry = self.ledger.get(self.account, appid) if self.account else {}
        state, pending = apply.status(entry, plan)
        view = GameView(appid, name, game, stats, native, ac, plan, state, pending, entry,
                        launch.get(str(appid), ""), mapping.get(str(appid)))
        if with_status and game is not None:
            self._refresh_status([view])
        return view

    def scan(self) -> list[GameView]:
        if not self.root:
            return []
        self.tools = system.tools_available()
        self.compat = steam.compat_tools(self.root)
        mapping = steam.compat_mapping(self.root)
        launch = self._launch_options()
        views = [self.view(g.appid, g.name, g, mapping, launch, with_status=False) for g in steam.games(self.root)]
        self._refresh_status(views)
        return views

    def _refresh_status(self, views: list[GameView]) -> None:
        installed = [v for v in views if v.installed]
        results = {r.appid: r for r in self.preview(installed)}
        for v in installed:
            r = results.get(v.appid)
            changes = len(r.added) + len(r.removed) if r else 0
            if changes == 0:
                v.status = "fixed" if v.entry else "nothing"
            else:
                v.status = "new" if v.entry else "ready"
            v.pending = changes

    def search(self, text: str) -> list[GameStats]:
        return self.index.search(text, limit=60)

    def fetch_online(self, appids: list[int]) -> None:
        for appid in appids:
            online.linux_native(appid)
            online.tier(appid)
        online.save()

    # Changes

    def preview(self, views: list[GameView]) -> list[apply.GameResult]:
        if not self.root or not self.account:
            return []
        plans = {v.appid: v.plan for v in views}
        return apply.apply_plans(self.root, self.account, plans, self.ledger, dry_run=True)

    def preview_launch(self, view: GameView) -> str:
        desired = view.plan.launch_tokens()
        texts = {t.text for t in desired}
        remove = [t for t in view.entry.get("tokens", []) if t not in texts]
        if view.entry.get("inserted_command") and not desired:
            remove.append(launchopts.COMMAND)
        return launchopts.merge(view.launch_now, desired, remove).text

    def needs_ge(self, views: list[GameView]) -> bool:
        return any(v.plan.proton() == GE_DOWNLOAD for v in views)

    def install_ge(self, progress: Progress | None = None) -> str:
        if not self.root:
            raise SteamMissing("Steam wasn't found")
        name = protonge.install(self.root, progress)
        self.compat = steam.compat_tools(self.root)
        return name

    def _with_steam_closed(self, work: Callable[[], object], progress: Progress | None, restart: bool):
        if not self.root or not self.account:
            raise SteamMissing("Steam wasn't found")
        was_running = steam.is_running()
        if was_running:
            if progress:
                progress(0.1, "Closing Steam")
            if not steam.shutdown(self.root):
                raise apply.SteamRunning("Steam didn't close. Close it yourself and try again.")
        try:
            return work()
        finally:
            if was_running and restart:
                if progress:
                    progress(0.95, "Starting Steam again")
                steam.start(self.root)

    def apply(self, appids: list[int], progress: Progress | None = None, restart: bool = True) -> list[apply.GameResult]:
        views = [v for v in self.scan() if v.appid in set(appids)]
        if self.needs_ge(views):
            self.install_ge(lambda f, t: progress and progress(f * 0.5, t))
            views = [v for v in self.scan() if v.appid in set(appids)]

        def work():
            if progress:
                progress(0.6, f"Applying fixes to {len(views)} game{'s' if len(views) != 1 else ''}")
            return apply.apply_plans(self.root, self.account, {v.appid: v.plan for v in views}, self.ledger,
                                     source=self.index.source)

        return self._with_steam_closed(work, progress, restart)

    def undo(self, appid: int, progress: Progress | None = None, restart: bool = True) -> apply.GameResult:
        return self._with_steam_closed(
            lambda: apply.undo(self.root, self.account, appid, self.ledger), progress, restart)

    def risky_games(self, views: list[GameView]) -> list[int]:
        return [v.appid for v in views if v.risky_applied]

    def set_account(self, account_id: int) -> None:
        self.settings.account_id = account_id
        self.settings.save()
        self.reload_steam()

    def with_settings(self, **changes) -> None:
        for k, v in changes.items():
            setattr(self.settings, k, v)
        self.settings.save()


def stats_view(service: Service, stats: GameStats, installed: dict[int, GameView]) -> GameView:
    if stats.appid in installed:
        return installed[stats.appid]
    return service.view(stats.appid, stats.title, None)


__all__ = ["GameView", "Service", "SteamMissing", "stats_view", "dataclasses"]
