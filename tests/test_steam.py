import unittest
from pathlib import Path
from unittest import mock

from mrrpmeowfix import steam

from . import fakesteam


class SteamTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.root_path, self.lib2 = fakesteam.build()
        self.root = steam.SteamRoot(self.root_path, "native")

    def tearDown(self):
        self.tmp.cleanup()

    def test_find_roots_from_home(self):
        home = self.root_path.parents[2]
        with mock.patch.object(Path, "home", return_value=home):
            roots = steam.find_roots()
        self.assertEqual([r.path for r in roots], [self.root_path.resolve()])
        self.assertEqual(roots[0].kind, "native")

    def test_libraries(self):
        libs = steam.libraries(self.root)
        self.assertEqual(libs, [self.root_path, self.lib2])

    def test_downloading_game_hidden_until_done(self):
        self.assertNotIn(2406770, [g.appid for g in steam.games(self.root)])
        acf = self.lib2 / "steamapps/appmanifest_2406770.acf"
        acf.write_text(acf.read_text().replace('"1026"', '"4"'))
        self.assertIn(2406770, [g.appid for g in steam.games(self.root)])

    def test_games_hide_tools(self):
        games = steam.games(self.root)
        names = sorted(g.name for g in games)
        self.assertEqual(names, ["Arma 3", "Barotrauma", "VRChat"])
        arma = next(g for g in games if g.appid == 107410)
        self.assertEqual(arma.installdir, self.lib2 / "steamapps/common/Arma 3")
        self.assertTrue(arma.has_prefix)
        baro = next(g for g in games if g.appid == 602960)
        self.assertFalse(baro.has_prefix)

    def test_current_account(self):
        acc = steam.current_account(self.root)
        self.assertEqual(acc.account_id, fakesteam.ACCOUNT_ID)
        self.assertEqual(acc.name, "player")
        self.assertEqual(acc.localconfig, self.root_path / f"userdata/{fakesteam.ACCOUNT_ID}/config/localconfig.vdf")
        self.assertEqual(len(steam.accounts(self.root)), 2)

    def test_compat_tools(self):
        tools = steam.compat_tools(self.root)
        names = [t.internal_name for t in tools]
        self.assertIn("GE-Proton11-11-x86_64", names)
        self.assertIn("proton_experimental", names)
        self.assertEqual(steam.newest_ge(tools).internal_name, "GE-Proton11-11-x86_64")

    def test_cover_path(self):
        self.assertTrue(steam.cover_path(self.root, 438100).name.endswith("600x900.jpg"))
        self.assertIsNone(steam.cover_path(self.root, 107410))

    def test_game_running(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            proc = Path(tmp)
            (proc / "123").mkdir()
            (proc / "123/environ").write_bytes(b"HOME=/x\0SteamAppId=438100\0")
            (proc / "456").mkdir()
            (proc / "456/environ").write_bytes(b"STEAM_COMPAT_APP_ID=107410\0")
            (proc / "self").mkdir()
            self.assertTrue(steam.game_running(438100, proc))
            self.assertTrue(steam.game_running(107410, proc))
            self.assertFalse(steam.game_running(4381, proc))

    def test_prefix_path(self):
        self.assertEqual(steam.prefix_path(self.root, 107410), self.root_path / "steamapps/compatdata/107410")
        self.assertIsNone(steam.prefix_path(self.root, 602960))

    def test_compat_mapping(self):
        self.assertEqual(steam.compat_mapping(self.root).get("438100"), "proton-cachyos-slr")


if __name__ == "__main__":
    unittest.main()
