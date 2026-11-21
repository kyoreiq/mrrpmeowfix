import unittest
from pathlib import Path

from mrrpmeowfix import apply, rules, steam, vdf
from mrrpmeowfix.index import GameStats
from mrrpmeowfix.steam import CompatTool

from . import fakesteam

GE = CompatTool("GE-Proton11-11-x86_64", "GE-Proton11-11", "ge")


def stats(lo=None, v=None, vb=None):
    b = {"n": 22, "g": 20, "f": 20, "w": "recent", "v": v or {}, "ge": {}, "lo": lo or {}, "vb": vb or {}}
    return GameStats(107410, "Arma 3", {"nvidia": b, "all": b})


class ApplyTests(unittest.TestCase):
    def setUp(self):
        self.tmp, root_path, _ = fakesteam.build({602960: 'bash -c "wget x && ./run %command%"'})
        self.root = steam.SteamRoot(root_path, "native")
        self.account = steam.current_account(self.root)
        self.ledger = apply.Ledger(Path(self.tmp.name) / "state.json")
        self.backups = Path(self.tmp.name) / "backups"
        self.originals = {p: p.read_text() for p in self.files()}
        self.verb_calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def files(self):
        return [self.account.localconfig, self.root.path / "config/config.vdf"]

    def ctx(self, risky_on=False, mapping=None, appid=107410):
        return rules.Context(gpu="nvidia", hybrid=False, risky_on=risky_on, overlay_on=False,
                             tools={"gamemoderun", "protontricks"}, compat_tools=[GE],
                             mapping=mapping if mapping is not None else steam.compat_mapping(self.root),
                             ours=self.ledger.get(self.account, appid))

    def plan(self, risky_on=False, s=None, anticheat=None):
        s = s or stats(lo={"PROTON_USE_WINED3D=1": 12, "-dx11": 10}, v={"ge": 15}, vb={"vcrun2019": 6})
        return rules.build_plan(107410, s, self.ctx(risky_on), native=False, anticheat=anticheat or [])

    def run_apply(self, plans, running=False):
        return apply.apply_plans(self.root, self.account, plans, self.ledger, source="test",
                                 backup_dir=self.backups, is_running=lambda: running,
                                 run_verbs=lambda appid, verbs: self.verb_calls.append((appid, verbs)) or None)

    def launch(self, appid):
        d = vdf.loads(self.account.localconfig.read_text())
        return (vdf.find(d, "UserLocalConfigStore", "Software", "Valve", "Steam", "apps", str(appid)) or {}).get("LaunchOptions")

    def test_apply_writes_launch_options_and_proton(self):
        [res] = self.run_apply({107410: self.plan()})
        self.assertEqual(self.launch(107410), "PROTON_ENABLE_NVAPI=1 __GL_SHADER_DISK_CACHE_SKIP_CLEANUP=1 gamemoderun %command% -dx11")
        self.assertEqual(steam.compat_mapping(self.root)["107410"], "GE-Proton11-11-x86_64")
        self.assertTrue(any("gamemoderun" in a for a in res.added))
        self.assertEqual(res.errors, [])
        self.assertEqual(self.verb_calls, [])  # vcrun2019 is risky and risky is off
        self.assertEqual(len(list(self.backups.iterdir())), 1)

    def test_risky_then_safe_cleans_up(self):
        self.run_apply({107410: self.plan(risky_on=True, anticheat=["BattlEye"])})
        self.assertEqual(self.launch(107410), "PROTON_ENABLE_NVAPI=1 __GL_SHADER_DISK_CACHE_SKIP_CLEANUP=1 PROTON_USE_WINED3D=1 gamemoderun %command% -dx11")
        self.assertEqual(steam.compat_mapping(self.root)["107410"], "GE-Proton11-11-x86_64")
        self.assertEqual(self.verb_calls, [(107410, ["vcrun2019"])])

        [res] = self.run_apply({107410: self.plan(risky_on=False, anticheat=["BattlEye"])})
        self.assertEqual(self.launch(107410), "__GL_SHADER_DISK_CACHE_SKIP_CLEANUP=1 gamemoderun %command%")
        self.assertNotIn("107410", steam.compat_mapping(self.root))
        self.assertTrue(any("PROTON_USE_WINED3D=1" in r for r in res.removed))
        self.assertTrue(any("vcrun2019" in n for n in res.notes))

    def test_restores_previous_proton_mapping(self):
        mapping_before = steam.compat_mapping(self.root)
        self.assertEqual(mapping_before["438100"], "proton-cachyos-slr")
        s = stats(v={"ge": 15})
        plan = rules.build_plan(438100, s, self.ctx(mapping={}, appid=438100), native=False, anticheat=[])
        self.run_apply({438100: plan})
        self.assertEqual(steam.compat_mapping(self.root)["438100"], "GE-Proton11-11-x86_64")
        apply.undo(self.root, self.account, 438100, self.ledger, backup_dir=self.backups, is_running=lambda: False)
        self.assertEqual(steam.compat_mapping(self.root)["438100"], "proton-cachyos-slr")

    def test_undo_restores_files(self):
        self.run_apply({107410: self.plan(), 602960: rules.build_plan(602960, None, self.ctx(appid=602960),
                                                                      native=True, anticheat=[])})
        self.assertEqual(self.launch(602960), '__GL_SHADER_DISK_CACHE_SKIP_CLEANUP=1 gamemoderun bash -c "wget x && ./run %command%"')
        for appid in (107410, 602960):
            apply.undo(self.root, self.account, appid, self.ledger, backup_dir=self.backups, is_running=lambda: False)
        for p in self.files():
            self.assertEqual(vdf.loads(p.read_text()), vdf.loads(self.originals[p]), p)
        self.assertIsNone(self.ledger.get(self.account, 107410).get("tokens"))

    def test_undo_after_user_edit_only_removes_ours(self):
        self.run_apply({107410: self.plan()})
        d = vdf.loads(self.account.localconfig.read_text())
        app = vdf.find(d, "UserLocalConfigStore", "Software", "Valve", "Steam", "apps", "107410")
        app["LaunchOptions"] = app["LaunchOptions"] + " -nosplash"
        self.account.localconfig.write_text(vdf.dumps(d))
        apply.undo(self.root, self.account, 107410, self.ledger, backup_dir=self.backups, is_running=lambda: False)
        self.assertEqual(self.launch(107410), "-nosplash")

    def test_refuses_while_steam_running(self):
        with self.assertRaises(apply.SteamRunning):
            self.run_apply({107410: self.plan()}, running=True)
        for p in self.files():
            self.assertEqual(p.read_text(), self.originals[p])

    def test_status(self):
        plan = self.plan()
        self.assertEqual(apply.status(self.ledger.get(self.account, 107410), plan), ("ready", 5))
        self.run_apply({107410: plan})
        self.assertEqual(apply.status(self.ledger.get(self.account, 107410), self.plan()), ("fixed", 0))
        changed = self.plan(s=stats(lo={"-dx11": 10, "-vulkan": 10}, v={"ge": 15}))
        self.assertEqual(apply.status(self.ledger.get(self.account, 107410), changed)[0], "new")
        self.assertEqual(apply.status({}, rules.Plan(1)), ("nothing", 0))

    def test_dry_run_changes_nothing(self):
        [res] = apply.apply_plans(self.root, self.account, {107410: self.plan()}, self.ledger,
                                  backup_dir=self.backups, is_running=lambda: True, dry_run=True)
        self.assertTrue(any("gamemoderun" in a for a in res.added))
        self.assertTrue(any("GE-Proton11-11" in a for a in res.added))
        for p in self.files():
            self.assertEqual(p.read_text(), self.originals[p])
        self.assertEqual(self.ledger.get(self.account, 107410), {})
        self.assertFalse(self.backups.exists())

    def test_backups_pruned(self):
        for _ in range(12):
            self.run_apply({107410: self.plan()})
        self.assertLessEqual(len(list(self.backups.iterdir())), apply.KEEP_BACKUPS)


if __name__ == "__main__":
    unittest.main()
