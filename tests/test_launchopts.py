import unittest

from mrrpmeowfix import launchopts as lo

GM = lo.sanitize("gamemoderun")
NVAPI = lo.sanitize("PROTON_ENABLE_NVAPI=1")
DX11 = lo.sanitize("-dx11")


class SanitizeTests(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(lo.sanitize("PROTON_LOG=1").kind, "env")
        self.assertEqual(lo.sanitize("PROTON_LOG=1").key, "PROTON_LOG")
        self.assertEqual(GM.kind, "wrapper")
        self.assertEqual(DX11.kind, "arg")
        self.assertEqual(lo.sanitize("-w 1920").kind, "arg")

    def test_rejects_shell(self):
        for bad in ["$(rm -rf ~)", "a;b", "/bin/x", "`id`", "FOO=$HOME", "FOO=/tmp/x",
                    "-x;rm", "curl", "A=1&&b", "FOO='x'", "-x|y", ""]:
            self.assertIsNone(lo.sanitize(bad), bad)


class SplitReportTests(unittest.TestCase):
    def test_split(self):
        toks = lo.split_report('PROTON_ENABLE_NVAPI=1 gamemoderun mangohud %command% -dx11 -w 1920 +exec x.cfg')
        self.assertEqual([t.text for t in toks],
                         ["PROTON_ENABLE_NVAPI=1", "gamemoderun", "mangohud", "-dx11", "-w 1920", "+exec x.cfg"])

    def test_quoted_value(self):
        toks = lo.split_report('WINEDLLOVERRIDES="dinput8=n,b" %command%')
        self.assertEqual([t.text for t in toks], ["WINEDLLOVERRIDES=dinput8=n,b"])

    def test_args_only_and_junk(self):
        self.assertEqual([t.text for t in lo.split_report("-vulkan")], ["-vulkan"])
        self.assertEqual(lo.split_report('bash -c "rm -rf ~" %command%'), [])
        self.assertEqual(lo.split_report('unbalanced "quote'), [])


class MergeTests(unittest.TestCase):
    def test_into_empty(self):
        r = lo.merge("", [NVAPI, GM, DX11], [])
        self.assertEqual(r.text, "PROTON_ENABLE_NVAPI=1 gamemoderun %command% -dx11")
        self.assertTrue(r.inserted_command)

    def test_wrapper_script(self):
        r = lo.merge("/home/u/.local/bin/cs2-launch %command%", [GM], [])
        self.assertEqual(r.text, "gamemoderun /home/u/.local/bin/cs2-launch %command%")

    def test_wrapper_after_user_env(self):
        cur = 'FOO="$XDG_RUNTIME_DIR/a b" %command%'
        r = lo.merge(cur, [NVAPI, GM], [])
        self.assertEqual(r.text, 'PROTON_ENABLE_NVAPI=1 FOO="$XDG_RUNTIME_DIR/a b" gamemoderun %command%')

    def test_bash_c_keeps_text_and_skips_args(self):
        cur = 'bash -c "wget x && ./run %command%"'
        r = lo.merge(cur, [DX11], [])
        self.assertEqual(r.text, cur)
        self.assertEqual([s[0] for s in r.skipped], ["-dx11"])
        r2 = lo.merge(cur, [GM], [])
        self.assertEqual(r2.text, "gamemoderun " + cur)

    def test_args_only(self):
        r = lo.merge("-windowed -w 1920", [GM], [])
        self.assertEqual(r.text, "gamemoderun %command% -windowed -w 1920")
        r2 = lo.merge("-windowed -w 1920", [DX11], [])
        self.assertEqual(r2.text, "-windowed -w 1920 -dx11")

    def test_unbalanced_quotes_skips_everything(self):
        cur = 'FOO="x %command%'
        r = lo.merge(cur, [GM, DX11], [])
        self.assertEqual(r.text, cur)
        self.assertEqual(len(r.skipped), 2)

    def test_top_level_operator_skips_everything(self):
        cur = "%command% ; echo done"
        r = lo.merge(cur, [GM], [])
        self.assertEqual(r.text, cur)
        self.assertEqual(len(r.skipped), 1)

    def test_no_duplicates(self):
        cur = "gamemoderun %command%"
        r = lo.merge(cur, [GM], [])
        self.assertEqual(r.text, cur)
        self.assertEqual(r.added, [])
        r2 = lo.merge("PROTON_ENABLE_NVAPI=0 %command%", [NVAPI], [])
        self.assertEqual(r2.text, "PROTON_ENABLE_NVAPI=0 %command%")
        self.assertEqual(r2.skipped[0][0], "PROTON_ENABLE_NVAPI=1")

    def test_remove_restores_original(self):
        for original in ["", "/home/u/bin/x %command%", "-windowed -w 1920",
                         'FOO="a b" %command% -nosplash', 'bash -c "x %command%"']:
            first = lo.merge(original, [NVAPI, GM, DX11], [])
            removed = first.added + (["%command%"] if first.inserted_command else [])
            back = lo.merge(first.text, [], removed)
            self.assertEqual(back.text, original, original)

    def test_remove_then_add(self):
        cur = "PROTON_USE_WINED3D=1 gamemoderun %command%"
        r = lo.merge(cur, [NVAPI], ["PROTON_USE_WINED3D=1"])
        self.assertEqual(r.text, "PROTON_ENABLE_NVAPI=1 gamemoderun %command%")
        self.assertEqual(r.removed, ["PROTON_USE_WINED3D=1"])


if __name__ == "__main__":
    unittest.main()
