"""Writes fixes into Steam's config files, remembers what we changed, and undoes it."""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import knowledge, launchopts, paths, steam, vdf
from .launchopts import COMMAND, sanitize
from .rules import GE_DOWNLOAD, Plan

KEEP_BACKUPS = 10
APPS_PATH = ("UserLocalConfigStore", "Software", "Valve", "Steam", "apps")
MAPPING_PATH = ("InstallConfigStore", "Software", "Valve", "Steam", "CompatToolMapping")


class SteamRunning(RuntimeError):
    pass


@dataclass
class GameResult:
    appid: int
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.added or self.removed)

    def to_json(self) -> dict:
        return {"added": self.added, "removed": self.removed, "skipped": self.skipped,
                "errors": self.errors, "notes": self.notes, "at": int(time.time())}


class Ledger:
    def __init__(self, path: Path | None = None):
        self.path = path or paths.data_dir() / "state.json"
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}
        self.data.setdefault("games", {})

    @staticmethod
    def _key(account: steam.Account, appid: int) -> str:
        return f"{account.account_id}/{appid}"

    def get(self, account: steam.Account, appid: int) -> dict:
        return self.data["games"].get(self._key(account, appid), {})

    def put(self, account: steam.Account, appid: int, entry: dict) -> None:
        self.data["games"][self._key(account, appid)] = entry

    def drop(self, account: steam.Account, appid: int) -> None:
        self.data["games"].pop(self._key(account, appid), None)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)


def _label(text: str) -> str:
    tok = sanitize(text)
    if tok is None:
        return text
    entry = knowledge.load().describe(tok)
    return f"{entry.label} ({text})" if entry.known else text


def _read_vdf(path: Path, top: str) -> dict:
    if path.exists():
        return vdf.loads(path.read_text(encoding="utf-8", errors="replace"))
    return {top: {}}


def _write_vdf(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".mrrpmeowfix-tmp")
    tmp.write_text(vdf.dumps(data), encoding="utf-8")
    if path.exists():
        shutil.copymode(path, tmp)
    os.replace(tmp, path)


def backup(files: list[Path], backup_dir: Path) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = backup_dir / stamp
    n = 1
    while target.exists():
        n += 1
        target = backup_dir / f"{stamp}-{n}"
    target.mkdir(parents=True)
    for f in files:
        if f.exists():
            shutil.copy2(f, target / f.name)
    olds = sorted(p for p in backup_dir.iterdir() if p.is_dir())
    for old in olds[:-KEEP_BACKUPS]:
        shutil.rmtree(old, ignore_errors=True)
    return target


def protontricks_install(appid: int, verbs: list[str]) -> str | None:
    if shutil.which("protontricks"):
        cmd = ["protontricks", str(appid), "-q"]
    elif shutil.which("flatpak"):
        cmd = ["flatpak", "run", "com.github.Matoking.protontricks", str(appid), "-q"]
    else:
        return "protontricks isn't installed."
    try:
        done = subprocess.run(cmd + verbs, capture_output=True, text=True, timeout=1800)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"protontricks failed: {e}"
    if done.returncode != 0:
        tail = (done.stderr or done.stdout).strip().splitlines()[-3:]
        return "protontricks failed: " + " ".join(tail)
    return None


def _wanted(plan: Plan) -> set[str]:
    out = {t.text for t in plan.launch_tokens()}
    if plan.proton():
        out.add("proton:" + plan.proton())
    out.update("verb:" + v for v in plan.verbs())
    return out


def _have(entry: dict) -> set[str]:
    out = set(entry.get("tokens", []))
    if entry.get("proton"):
        out.add("proton:" + entry["proton"])
    out.update("verb:" + v for v in entry.get("verbs", []))
    return out


def status(entry: dict, plan: Plan) -> tuple[str, int]:
    """('nothing'|'ready'|'fixed'|'new', number of pending changes)."""
    wanted = _wanted(plan)
    if not entry:
        return ("ready", len(wanted)) if wanted else ("nothing", 0)
    have = _have(entry)
    # Installed verbs can't be taken back, so they don't count as pending.
    pending = (wanted - have) | {x for x in have - wanted if not x.startswith("verb:")}
    return ("fixed", 0) if not pending else ("new", len(pending))


def _files(root: steam.SteamRoot, account: steam.Account) -> list[Path]:
    return [account.localconfig, root.path / "config/config.vdf"]


def apply_plans(
    root: steam.SteamRoot,
    account: steam.Account,
    plans: dict[int, Plan],
    ledger: Ledger,
    source: str = "",
    backup_dir: Path | None = None,
    is_running: Callable[[], bool] = steam.is_running,
    run_verbs: Callable[[int, list[str]], str | None] = protontricks_install,
    dry_run: bool = False,
) -> list[GameResult]:
    """Apply plans. With dry_run, nothing is written and the results describe what would happen."""
    if not dry_run:
        if is_running():
            raise SteamRunning("Steam is running")
        backup(_files(root, account), backup_dir or paths.data_dir() / "backups")

    local = _read_vdf(account.localconfig, "UserLocalConfigStore")
    config = _read_vdf(root.path / "config/config.vdf", "InstallConfigStore")
    apps = vdf.ensure(local, *APPS_PATH)
    mapping = vdf.ensure(config, *MAPPING_PATH)
    results: list[GameResult] = []
    verb_jobs: list[tuple[int, list[str], GameResult, dict]] = []

    for appid, plan in plans.items():
        key = str(appid)
        res = GameResult(appid)
        entry = copy.deepcopy(ledger.get(account, appid))
        entry.setdefault("tokens", [])
        entry.setdefault("verbs", [])

        # Launch options
        app = apps.get(key) if isinstance(apps.get(key), dict) else None
        current = app.get("LaunchOptions", "") if app else ""
        if "launch_before" not in entry:
            entry["launch_before"] = current
            entry["launch_existed"] = bool(app and "LaunchOptions" in app)
            entry["app_existed"] = app is not None
        desired = plan.launch_tokens()
        desired_texts = {t.text for t in desired}
        remove = [t for t in entry["tokens"] if t not in desired_texts]
        if entry.get("inserted_command") and not desired:
            remove.append(COMMAND)
        merged = launchopts.merge(current, desired, remove)
        res.skipped += [f"{_label(text)}: {why}" for text, why in merged.skipped]
        if merged.skipped and merged.text == current and not merged.added and not merged.removed and remove:
            kept = entry["tokens"]
        else:
            kept = [t for t in entry["tokens"] if t not in merged.removed and t in desired_texts] + merged.added
        entry["tokens"] = kept
        if merged.inserted_command:
            entry["inserted_command"] = True
        if COMMAND in merged.removed:
            entry["inserted_command"] = False
        res.added += [_label(t) for t in merged.added]
        res.removed += [_label(t) for t in merged.removed if t != COMMAND]
        if merged.text != current:
            if app is None:
                app = apps[key] = {}
            app["LaunchOptions"] = merged.text
        entry["launch_written"] = merged.text

        # Proton version
        want = plan.proton()
        now_map = mapping.get(key) if isinstance(mapping.get(key), dict) else None
        now_name = now_map.get("name") if now_map else None
        if want == GE_DOWNLOAD:
            res.skipped.append("GE-Proton isn't installed, so the Proton version wasn't changed.")
            want = None if entry.get("proton") is None else entry["proton"]
        if want:
            if now_name != want:
                if "proton_before" not in entry:
                    entry["proton_before"] = copy.deepcopy(now_map)
                mapping[key] = {"name": want, "config": "", "priority": "250"}
                res.added.append(f"Proton version: {want}")
            entry["proton"] = want
        elif entry.get("proton"):
            if now_name == entry["proton"]:
                before = entry.get("proton_before")
                if before:
                    mapping[key] = before
                    res.removed.append(f"Proton version {entry['proton']} (back to {before.get('name')})")
                else:
                    mapping.pop(key, None)
                    res.removed.append(f"Proton version {entry['proton']} (back to Steam's default)")
            entry["proton"] = None
            entry.pop("proton_before", None)

        # Windows components
        stale = [v for v in entry["verbs"] if v not in plan.verbs()]
        if stale:
            res.notes.append(
                f"{', '.join(stale)} stays installed: it can't be removed automatically. To get rid of it, "
                f"delete this game's Proton files (steamapps/compatdata/{appid}). That also deletes saves kept there."
            )
        new_verbs = [v for v in plan.verbs() if v not in entry["verbs"]]
        if new_verbs:
            verb_jobs.append((appid, new_verbs, res, entry))

        entry["risky"] = sorted(plan.risky_values() & (desired_texts | {plan.proton() or ""} | set(plan.verbs())))
        entry["source"] = source
        entry["applied_at"] = int(time.time())
        res.notes += plan.notes
        if not dry_run:
            ledger.put(account, appid, entry)
        results.append(res)

    if dry_run:
        for _, verbs, res, _ in verb_jobs:
            res.added += [f"Install {v} with protontricks" for v in verbs]
        return results

    _write_vdf(account.localconfig, local)
    _write_vdf(root.path / "config/config.vdf", config)
    ledger.save()

    for appid, verbs, res, entry in verb_jobs:
        error = run_verbs(appid, verbs)
        if error:
            res.errors.append(error)
        else:
            entry["verbs"] = entry["verbs"] + verbs
            res.added += [f"Installed {v} with protontricks" for v in verbs]
    for res in results:
        entry = ledger.get(account, res.appid)
        entry["last_result"] = res.to_json()
    ledger.save()
    return results


def undo(
    root: steam.SteamRoot,
    account: steam.Account,
    appid: int,
    ledger: Ledger,
    backup_dir: Path | None = None,
    is_running: Callable[[], bool] = steam.is_running,
) -> GameResult:
    if is_running():
        raise SteamRunning("Steam is running")
    res = GameResult(appid)
    entry = ledger.get(account, appid)
    if not entry:
        return res
    backup(_files(root, account), backup_dir or paths.data_dir() / "backups")
    key = str(appid)

    local = _read_vdf(account.localconfig, "UserLocalConfigStore")
    apps = vdf.ensure(local, *APPS_PATH)
    app = apps.get(key) if isinstance(apps.get(key), dict) else None
    if app is not None:
        current = app.get("LaunchOptions", "")
        if current == entry.get("launch_written"):
            restored = entry.get("launch_before", "")
        else:
            remove = list(entry.get("tokens", [])) + ([COMMAND] if entry.get("inserted_command") else [])
            restored = launchopts.merge(current, [], remove).text
        res.removed += [_label(t) for t in entry.get("tokens", [])]
        if restored == "" and not entry.get("launch_existed"):
            app.pop("LaunchOptions", None)
            if not app and not entry.get("app_existed"):
                apps.pop(key, None)
        else:
            app["LaunchOptions"] = restored

    config = _read_vdf(root.path / "config/config.vdf", "InstallConfigStore")
    mapping = vdf.ensure(config, *MAPPING_PATH)
    ours = entry.get("proton")
    now_map = mapping.get(key) if isinstance(mapping.get(key), dict) else None
    if ours and now_map and now_map.get("name") == ours:
        before = entry.get("proton_before")
        if before:
            mapping[key] = before
        else:
            mapping.pop(key, None)
        res.removed.append(f"Proton version {ours}")

    if entry.get("verbs"):
        res.notes.append(f"{', '.join(entry['verbs'])} stays installed in the game's Proton files.")

    _write_vdf(account.localconfig, local)
    _write_vdf(root.path / "config/config.vdf", config)
    ledger.drop(account, appid)
    ledger.save()
    return res
