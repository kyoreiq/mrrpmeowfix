"""Turns report statistics into a list of fixes for one game."""

from __future__ import annotations

from dataclasses import dataclass, field

from . import knowledge
from .index import MIN_GOOD, GameStats
from .knowledge import NEVER, NORMAL, RISKY
from .launchopts import Token, sanitize
from .steam import CompatTool, newest_ge

GE_DOWNLOAD = "ge-proton-latest"

TOKEN_SHARE = 0.20
TOKEN_MIN = 3
UNKNOWN_ARG_SHARE = 0.40
UNKNOWN_ARG_MIN = 5
PROTON_SHARE = 0.40
VERB_SHARE = 0.15
VERB_MIN = 3

BASE_WRAPPERS = ("gamemoderun", "game-performance")
NVIDIA_BASE = "PROTON_ENABLE_NVAPI=1"
NVIDIA_SHADER_CACHE = "__GL_SHADER_DISK_CACHE_SKIP_CLEANUP=1"
MESA_SHADER_CACHE = "MESA_SHADER_CACHE_MAX_SIZE=10G"
WINDOWS_ONLY_PREFIXES = ("PROTON_", "DXVK_", "VKD3D_", "WINE")

GPU_LABEL = {"nvidia": "NVIDIA ", "amd": "AMD ", "intel": "Intel ", "all": ""}

RISKY_BLOCK = "Risky fix. Turn on Risky fixes in Settings to use it."
TOOL_BLOCK = {
    "gamemoderun": "GameMode isn't installed. See Your PC.",
    "game-performance": "game-performance isn't installed.",
    "mangohud": "MangoHud isn't installed. See Your PC.",
    "protontricks": "Needs protontricks. See Your PC.",
    "prime-run": "prime-run isn't installed (it comes with the NVIDIA PRIME package).",
}


@dataclass
class Context:
    gpu: str
    hybrid: bool
    risky_on: bool
    overlay_on: bool
    tools: set[str]
    compat_tools: list[CompatTool]
    mapping: dict[str, str]
    ours: dict = field(default_factory=dict)


@dataclass
class FixItem:
    kind: str  # launch | proton | verb
    value: str
    label: str
    about: str
    evidence: str
    risky: bool = False
    blocked: str | None = None
    token: Token | None = None


@dataclass
class Plan:
    appid: int
    items: list[FixItem] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    bucket: str | None = None
    good_reports: int = 0

    def active(self) -> list[FixItem]:
        return [i for i in self.items if i.blocked is None]

    def launch_tokens(self) -> list[Token]:
        return [i.token for i in self.active() if i.kind == "launch" and i.token]

    def proton(self) -> str | None:
        return next((i.value for i in self.active() if i.kind == "proton"), None)

    def verbs(self) -> list[str]:
        return [i.value for i in self.active() if i.kind == "verb"]

    def risky_values(self) -> set[str]:
        return {i.value for i in self.items if i.risky}


def _pct(count: int, total: int) -> int:
    return round(100 * count / total) if total else 0


FIXLIST_EVIDENCE = "From the mrrpmeowfix fix list."


def build_plan(appid: int, stats: GameStats | None, ctx: Context, native: bool, anticheat: list[str],
               fixlist: dict | None = None) -> Plan:
    know = knowledge.load()
    plan = Plan(appid)
    has_ac = bool(anticheat)
    fixlist = fixlist or {}
    blocked_texts = {b for b in fixlist.get("block", []) if "=" in b or " " in b}
    blocked_keys = {b for b in fixlist.get("block", []) if b not in blocked_texts}

    def gate(item: FixItem, needs: str | None = None) -> FixItem:
        if needs and needs not in ctx.tools:
            item.blocked = TOOL_BLOCK.get(needs, f"{needs} isn't installed.")
        elif item.risky and not ctx.risky_on:
            item.blocked = RISKY_BLOCK
        plan.items.append(item)
        return item

    def is_blocked(tok: Token) -> bool:
        return tok.text in blocked_texts or tok.key in blocked_keys

    def launch_item(tok: Token, evidence: str, needs: str | None = None, share: float = 1.0, count: int = 0,
                    vouched: bool = False) -> None:
        if is_blocked(tok):
            return
        entry = know.classify(tok, ctx.gpu, has_ac, ctx.hybrid)
        level = entry.level
        if level == NEVER:
            return
        if vouched and not entry.known:
            level = RISKY if has_ac else NORMAL
        elif not entry.known and tok.kind == "arg" and level == NORMAL and not has_ac:
            if share < UNKNOWN_ARG_SHARE or count < UNKNOWN_ARG_MIN:
                level = RISKY
        gate(FixItem("launch", tok.text, entry.label, entry.about, evidence, level == RISKY, token=tok), needs)

    if stats is None or stats.total == 0:
        plan.notes.append("No reports yet for this game, so only the basic tweaks are used.")
        bucket_name, bucket = "all", None
    else:
        bucket_name, bucket = stats.bucket(ctx.gpu)
        if bucket_name == "all" and ctx.gpu in GPU_LABEL and ctx.gpu != "all":
            plan.notes.append(f"Not many {GPU_LABEL[ctx.gpu].strip()} reports yet, so reports from every GPU are used.")
    good = bucket["g"] if bucket else 0
    plan.bucket, plan.good_reports = bucket_name, good
    label = GPU_LABEL.get(bucket_name, "")

    if fixlist.get("note"):
        plan.notes.insert(0, f"Note from the fix list: {fixlist['note']}")
    if native:
        plan.notes.append("Runs natively on Linux, so Proton fixes don't apply.")
    if has_ac:
        plan.notes.append(f"Uses {', '.join(anticheat)}. Only safe tweaks are applied unless Risky fixes is on.")

    for wrapper in BASE_WRAPPERS:
        if wrapper == "game-performance" and wrapper not in ctx.tools:
            continue
        launch_item(sanitize(wrapper), "Recommended for every game.", needs=wrapper)
    if ctx.hybrid and ctx.gpu == "nvidia":
        launch_item(sanitize("prime-run"), "Your laptop has two GPUs; this keeps games on the NVIDIA one.",
                    needs="prime-run")
    if ctx.overlay_on:
        gate(FixItem("launch", "mangohud", "MangoHud overlay", "Shows FPS, frame times and temperatures.",
                     "You turned on the FPS overlay in Settings.", token=sanitize("mangohud")), "mangohud")
    if ctx.gpu == "nvidia":
        if not native:
            launch_item(sanitize(NVIDIA_BASE), "Recommended for NVIDIA cards.")
        launch_item(sanitize(NVIDIA_SHADER_CACHE), "Recommended for NVIDIA cards.")
    elif ctx.gpu in ("amd", "intel"):
        launch_item(sanitize(MESA_SHADER_CACHE), "Recommended for AMD and Intel graphics.")

    for text in fixlist.get("add", []):
        tok = sanitize(text)
        if tok is None or (native and tok.kind == "env" and tok.key.startswith(WINDOWS_ONLY_PREFIXES)):
            continue
        if any(i.token and i.token.key == tok.key for i in plan.items):
            continue
        launch_item(tok, FIXLIST_EVIDENCE, needs=tok.key if tok.kind == "wrapper" else None, vouched=True)

    taken = {i.token.key for i in plan.items if i.token}
    if bucket and good:
        best_by_key: dict[str, tuple[int, Token]] = {}
        for text, count in bucket.get("lo", {}).items():
            tok = sanitize(text)
            if tok is None or tok.kind == "wrapper" or tok.key in taken:
                continue
            if native and tok.kind == "env" and tok.key.startswith(WINDOWS_ONLY_PREFIXES):
                continue
            if count < TOKEN_MIN or count / good < TOKEN_SHARE:
                continue
            if tok.key not in best_by_key or count > best_by_key[tok.key][0]:
                best_by_key[tok.key] = (count, tok)
        for count, tok in sorted(best_by_key.values(), key=lambda x: -x[0]):
            launch_item(tok, f"Used in {_pct(count, good)}% of {good} {label}reports where the game worked.",
                        share=count / good, count=count)

    if not native:
        _proton_item(plan, ctx, bucket if good >= MIN_GOOD else None, good, label, has_ac, gate, str(appid),
                     fixlist.get("proton"))

    if not native and bucket and good:
        for verb, count in sorted(bucket.get("vb", {}).items(), key=lambda x: -x[1]):
            if count < VERB_MIN or count / good < VERB_SHARE or verb in blocked_keys:
                continue
            gate(FixItem("verb", verb, f"Install {verb}",
                         "Installs a Windows component into this game's Proton files with protontricks. "
                         "It can't be removed again without resetting the game's Proton files.",
                         f"Mentioned in {_pct(count, good)}% of {good} {label}reports where the game worked.",
                         risky=True), "protontricks")
    return plan


def _proton_item(plan, ctx: Context, bucket: dict | None, good: int, label: str, has_ac: bool, gate, key: str,
                 forced: str | None = None) -> None:
    pick = None
    if forced in ("ge", "experimental", "default"):
        if forced == "default":
            return
        pick, evidence = forced, FIXLIST_EVIDENCE
    elif bucket:
        v = bucket.get("v", {})
        ge, exp, official = v.get("ge", 0), v.get("experimental", 0), v.get("official", 0)
        if ge / good >= PROTON_SHARE and ge > exp and ge > official:
            pick = "ge"
            evidence = f"{_pct(ge, good)}% of {good} {label}reports where the game worked used GE-Proton."
        elif exp / good >= PROTON_SHARE:
            pick = "experimental"
            evidence = f"{_pct(exp, good)}% of {good} {label}reports where the game worked used Proton Experimental."
    if pick is None:
        return
    if pick == "ge":
        tool = newest_ge(ctx.compat_tools)
        target = tool.internal_name if tool else GE_DOWNLOAD
        name = tool.display if tool else "GE-Proton (newest)"
    else:
        target, name = "proton_experimental", "Proton Experimental"
    current = ctx.mapping.get(key, "")
    if current and current != ctx.ours.get("proton"):
        if current != target:
            plan.notes.append(f"You picked {current} for this game yourself, so the Proton version was left alone.")
        return
    gate(FixItem(
        "proton", target, f"Use {name}",
        "Runs the game with this Proton version instead of Steam's default.",
        evidence,
        risky=has_ac,
    ))
