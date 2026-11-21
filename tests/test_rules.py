import tempfile
import unittest
from pathlib import Path

from mrrpmeowfix import anticheat, rules
from mrrpmeowfix.index import GameStats
from mrrpmeowfix.steam import CompatTool

GE = CompatTool("GE-Proton11-11-x86_64", "GE-Proton11-11", "ge")
EXP = CompatTool("proton_experimental", "Proton Experimental", "valve")


def stats(g=20, v=None, lo=None, vb=None, ge=None):
    bucket = {"n": g + 2, "g": g, "f": g, "w": "recent", "v": v or {}, "ge": ge or {}, "lo": lo or {}, "vb": vb or {}}
    return GameStats(10, "Game", {"nvidia": bucket, "all": bucket})


def ctx(**kw):
    base = dict(gpu="nvidia", hybrid=False, risky_on=False, overlay_on=False,
                tools={"gamemoderun", "protontricks"}, compat_tools=[GE, EXP], mapping={}, ours={})
    base.update(kw)
    return rules.Context(**base)


def values(plan, kind=None, applicable=True):
    return [i.value for i in plan.items if (kind is None or i.kind == kind) and (not applicable or i.blocked is None)]


class RuleTests(unittest.TestCase):
    def test_ge_majority(self):
        plan = rules.build_plan(10, stats(v={"ge": 10, "official": 6, "experimental": 4}), ctx(), native=False, anticheat=[])
        self.assertEqual(values(plan, "proton"), ["GE-Proton11-11-x86_64"])
        self.assertIn("50%", next(i for i in plan.items if i.kind == "proton").evidence)

    def test_experimental(self):
        plan = rules.build_plan(10, stats(v={"experimental": 9, "official": 6, "ge": 5}), ctx(), native=False, anticheat=[])
        self.assertEqual(values(plan, "proton"), ["proton_experimental"])

    def test_default_when_no_majority(self):
        plan = rules.build_plan(10, stats(v={"official": 15, "ge": 5}), ctx(), native=False, anticheat=[])
        self.assertEqual(values(plan, "proton", applicable=False), [])

    def test_ge_needs_download(self):
        plan = rules.build_plan(10, stats(v={"ge": 15}), ctx(compat_tools=[EXP]), native=False, anticheat=[])
        item = next(i for i in plan.items if i.kind == "proton")
        self.assertEqual(item.value, rules.GE_DOWNLOAD)
        self.assertIsNone(item.blocked)

    def test_anticheat_proton_switch_is_risky(self):
        plan = rules.build_plan(10, stats(v={"ge": 15}), ctx(), native=False, anticheat=["Easy Anti-Cheat"])
        item = next(i for i in plan.items if i.kind == "proton")
        self.assertTrue(item.risky)
        self.assertIsNotNone(item.blocked)
        on = rules.build_plan(10, stats(v={"ge": 15}), ctx(risky_on=True), native=False, anticheat=["Easy Anti-Cheat"])
        self.assertEqual(values(on, "proton"), ["GE-Proton11-11-x86_64"])

    def test_anticheat_keeps_gamemode_only(self):
        plan = rules.build_plan(10, stats(lo={"-dx11": 15}), ctx(), native=False, anticheat=["BattlEye"])
        self.assertEqual(values(plan, "launch"), ["gamemoderun", "__GL_SHADER_DISK_CACHE_SKIP_CLEANUP=1"])

    def test_user_picked_proton_left_alone(self):
        plan = rules.build_plan(10, stats(v={"ge": 15}), ctx(mapping={"10": "proton-cachyos-slr"}), native=False, anticheat=[])
        self.assertEqual(values(plan, "proton", applicable=False), [])
        self.assertTrue(any("proton-cachyos-slr" in n for n in plan.notes))
        ours = rules.build_plan(10, stats(v={"ge": 15}), ctx(mapping={"10": "GE-Proton11-7-x86_64"},
                                ours={"proton": "GE-Proton11-7-x86_64"}), native=False, anticheat=[])
        self.assertEqual(values(ours, "proton"), ["GE-Proton11-11-x86_64"])

    def test_never_and_thresholds(self):
        lo = {"PROTON_LOG=1": 15, "-dx11": 10, "-rare": 3, "-popular": 9, "PROTON_FORCE_LARGE_ADDRESS_AWARE=1": 5}
        plan = rules.build_plan(10, stats(lo=lo), ctx(), native=False, anticheat=[])
        launch = values(plan, "launch")
        self.assertNotIn("PROTON_LOG=1", values(plan, "launch", applicable=False))
        self.assertIn("-dx11", launch)
        self.assertIn("-popular", launch)  # unknown arg, 45% of 20 good reports
        self.assertIn("PROTON_FORCE_LARGE_ADDRESS_AWARE=1", launch)
        self.assertNotIn("-rare", values(plan, "launch", applicable=False))  # 15%, under 20%

    def test_risky_token_gated(self):
        lo = {"PROTON_USE_WINED3D=1": 12}
        off = rules.build_plan(10, stats(lo=lo), ctx(), native=False, anticheat=[])
        self.assertNotIn("PROTON_USE_WINED3D=1", values(off, "launch"))
        self.assertIn("PROTON_USE_WINED3D=1", values(off, "launch", applicable=False))
        on = rules.build_plan(10, stats(lo=lo), ctx(risky_on=True), native=False, anticheat=[])
        self.assertIn("PROTON_USE_WINED3D=1", values(on, "launch"))

    def test_same_key_keeps_most_common(self):
        lo = {"WINEDLLOVERRIDES=xinput1_4=n,b": 9, "WINEDLLOVERRIDES=XInput1_4=n,b": 6}
        plan = rules.build_plan(10, stats(lo=lo), ctx(risky_on=True), native=False, anticheat=[])
        self.assertEqual([v for v in values(plan, "launch") if v.startswith("WINEDLL")], ["WINEDLLOVERRIDES=xinput1_4=n,b"])

    def test_overlay(self):
        plan = rules.build_plan(10, stats(), ctx(), native=False, anticheat=[])
        self.assertNotIn("mangohud", values(plan, "launch", applicable=False))
        on = rules.build_plan(10, stats(), ctx(overlay_on=True, tools={"gamemoderun", "mangohud"}), native=False, anticheat=[])
        self.assertIn("mangohud", values(on, "launch"))

    def test_native(self):
        plan = rules.build_plan(10, stats(v={"ge": 15}, lo={"PROTON_ENABLE_NVAPI=1": 15, "-vulkan": 10}), ctx(),
                                native=True, anticheat=[])
        self.assertEqual(values(plan, "proton", applicable=False), [])
        self.assertEqual(values(plan, "launch"), ["gamemoderun", "__GL_SHADER_DISK_CACHE_SKIP_CLEANUP=1", "-vulkan"])

    def test_nvapi_base_on_nvidia_only(self):
        self.assertIn("PROTON_ENABLE_NVAPI=1", values(rules.build_plan(10, stats(), ctx(), native=False, anticheat=[]), "launch"))
        amd = rules.build_plan(10, stats(), ctx(gpu="amd"), native=False, anticheat=[])
        self.assertNotIn("PROTON_ENABLE_NVAPI=1", values(amd, "launch", applicable=False))
        self.assertIn("MESA_SHADER_CACHE_MAX_SIZE=10G", values(amd, "launch"))

    def test_verbs_risky_and_need_protontricks(self):
        plan = rules.build_plan(10, stats(vb={"vcrun2019": 6}), ctx(risky_on=True), native=False, anticheat=[])
        self.assertEqual(values(plan, "verb"), ["vcrun2019"])
        missing = rules.build_plan(10, stats(vb={"vcrun2019": 6}), ctx(risky_on=True, tools={"gamemoderun"}),
                                   native=False, anticheat=[])
        self.assertEqual(values(missing, "verb"), [])
        self.assertIn("protontricks", next(i for i in missing.items if i.kind == "verb").blocked)

    def test_unknown_game(self):
        plan = rules.build_plan(10, None, ctx(), native=False, anticheat=[])
        self.assertEqual(values(plan, "launch"), ["gamemoderun", "PROTON_ENABLE_NVAPI=1", "__GL_SHADER_DISK_CACHE_SKIP_CLEANUP=1"])
        self.assertTrue(any("No reports yet" in n for n in plan.notes))

    def test_prime_run_on_hybrid_laptop(self):
        plan = rules.build_plan(10, stats(), ctx(hybrid=True, tools={"gamemoderun", "prime-run"}), native=False, anticheat=[])
        self.assertIn("prime-run", values(plan, "launch"))
        desk = rules.build_plan(10, stats(), ctx(tools={"gamemoderun", "prime-run"}), native=False, anticheat=[])
        self.assertNotIn("prime-run", values(desk, "launch", applicable=False))

    def test_missing_gamemode_is_blocked(self):
        plan = rules.build_plan(10, stats(), ctx(tools=set()), native=False, anticheat=[])
        gm = next(i for i in plan.items if i.value == "gamemoderun")
        self.assertIn("GameMode", gm.blocked)


class FixListTests(unittest.TestCase):
    def test_add_block_note(self):
        fl = {"add": ["-dx11", "PROTON_ENABLE_NTSYNC=1", "$(evil)"], "block": ["gamemoderun", "PROTON_ENABLE_NVAPI"],
              "note": "Crashes without -dx11."}
        plan = rules.build_plan(10, stats(lo={"-vulkan": 12}), ctx(), native=False, anticheat=[], fixlist=fl)
        launch = values(plan, "launch")
        self.assertIn("-dx11", launch)
        self.assertIn("PROTON_ENABLE_NTSYNC=1", launch)  # unknown, but the list vouches for it
        self.assertNotIn("gamemoderun", values(plan, "launch", applicable=False))
        self.assertNotIn("PROTON_ENABLE_NVAPI=1", values(plan, "launch", applicable=False))
        self.assertNotIn("$(evil)", values(plan, "launch", applicable=False))
        self.assertEqual(plan.notes[0], "Note from the fix list: Crashes without -dx11.")
        item = next(i for i in plan.items if i.value == "-dx11")
        self.assertEqual(item.evidence, rules.FIXLIST_EVIDENCE)

    def test_list_cannot_bypass_safety(self):
        fl = {"add": ["PROTON_LOG=1", "PROTON_USE_WINED3D=1", "NEW_THING=1"]}
        plan = rules.build_plan(10, None, ctx(), native=False, anticheat=[], fixlist=fl)
        self.assertNotIn("PROTON_LOG=1", values(plan, "launch", applicable=False))
        self.assertNotIn("PROTON_USE_WINED3D=1", values(plan, "launch"))
        self.assertIn("PROTON_USE_WINED3D=1", values(plan, "launch", applicable=False))
        ac = rules.build_plan(10, None, ctx(), native=False, anticheat=["EAC"], fixlist=fl)
        self.assertNotIn("NEW_THING=1", values(ac, "launch"))

    def test_proton_override(self):
        s = stats(v={"ge": 15})
        exp = rules.build_plan(10, s, ctx(), native=False, anticheat=[], fixlist={"proton": "experimental"})
        self.assertEqual(values(exp, "proton"), ["proton_experimental"])
        none = rules.build_plan(10, s, ctx(), native=False, anticheat=[], fixlist={"proton": "default"})
        self.assertEqual(values(none, "proton", applicable=False), [])
        new_game = rules.build_plan(10, None, ctx(), native=False, anticheat=[], fixlist={"proton": "ge"})
        self.assertEqual(values(new_game, "proton"), ["GE-Proton11-11-x86_64"])
        mine = rules.build_plan(10, None, ctx(mapping={"10": "proton-cachyos-slr"}), native=False, anticheat=[],
                                fixlist={"proton": "ge"})
        self.assertEqual(values(mine, "proton", applicable=False), [])

    def test_block_verb(self):
        plan = rules.build_plan(10, stats(vb={"vcrun2019": 6}), ctx(risky_on=True), native=False, anticheat=[],
                                fixlist={"block": ["vcrun2019"]})
        self.assertEqual(values(plan, "verb", applicable=False), [])


class AntiCheatTests(unittest.TestCase):
    def test_by_id_name_and_folder(self):
        ac = anticheat.AntiCheat([
            {"n": "VRChat", "s": "Supported", "a": ["Easy Anti-Cheat"], "id": "438100"},
            {"n": "Counter-Strike 2", "s": "Supported", "a": ["VAC"], "id": ""},
            {"n": "Counter-Strike 2 (FACEIT)", "s": "Denied", "a": ["FACEIT"], "id": ""},
        ])
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            self.assertEqual(ac.check(438100, "VRChat", d), ["Easy Anti-Cheat"])
            self.assertEqual(ac.check(730, "Counter-Strike 2", d), ["VAC"])
            self.assertEqual(ac.check(1, "Some Game", d), [])
            (d / "BattlEye").mkdir()
            self.assertEqual(ac.check(1, "Some Game", d), ["BattlEye"])

    def test_bundled_loads(self):
        self.assertIn("Easy Anti-Cheat", anticheat.load().check(438100, "VRChat", Path("/nonexistent")))


if __name__ == "__main__":
    unittest.main()
