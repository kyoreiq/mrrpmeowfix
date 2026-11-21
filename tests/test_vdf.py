import unittest

from mrrpmeowfix import vdf

LOCALCONFIG = r'''"UserLocalConfigStore"
{
	"Software"
	{
		"Valve"
		{
			"Steam"
			{
				"apps"
				{
					"438100"
					{
						"LaunchOptions"		"FOO=\"$XDG_RUNTIME_DIR/x\" gamemoderun %command%"
						"LastPlayed"		"1795263957"
					}
					"250900"
					{
						"LaunchOptions"		"bash -c \"a \\\\ b %command%\""
					}
				}
			}
		}
	}
	"empty"		""
}
'''

COMPAT_TOOL = '''"compatibilitytools"
{
  "compat_tools"
  {
    "GE-Proton11-11-x86_64" // Internal name of this tool
    {
      "install_path" "."
      "display_name" "GE-Proton11-11"
      "from_oslist"  "windows"
      "to_oslist"    "linux"
    }
  }
}
'''


class VdfTests(unittest.TestCase):
    def test_parses_escaped_quotes(self):
        d = vdf.loads(LOCALCONFIG)
        app = d["UserLocalConfigStore"]["Software"]["Valve"]["Steam"]["apps"]["438100"]
        self.assertEqual(app["LaunchOptions"], 'FOO="$XDG_RUNTIME_DIR/x" gamemoderun %command%')

    def test_parses_escaped_backslash(self):
        d = vdf.loads(LOCALCONFIG)
        app = d["UserLocalConfigStore"]["Software"]["Valve"]["Steam"]["apps"]["250900"]
        self.assertEqual(app["LaunchOptions"], 'bash -c "a \\\\ b %command%"')

    def test_round_trip(self):
        d = vdf.loads(LOCALCONFIG)
        self.assertEqual(vdf.loads(vdf.dumps(d)), d)

    def test_dump_matches_steam_layout(self):
        d = vdf.loads(LOCALCONFIG)
        self.assertEqual(vdf.dumps(d), LOCALCONFIG)

    def test_comments_ignored(self):
        d = vdf.loads(COMPAT_TOOL)
        tools = d["compatibilitytools"]["compat_tools"]
        self.assertEqual(list(tools), ["GE-Proton11-11-x86_64"])
        self.assertEqual(tools["GE-Proton11-11-x86_64"]["display_name"], "GE-Proton11-11")

    def test_find_is_case_insensitive(self):
        d = vdf.loads(LOCALCONFIG)
        apps = vdf.find(d, "userlocalconfigstore", "software", "valve", "steam", "Apps")
        self.assertIn("438100", apps)
        self.assertIsNone(vdf.find(d, "nope", "x"))

    def test_ensure_reuses_existing_case(self):
        d = vdf.loads(LOCALCONFIG)
        apps = vdf.ensure(d, "UserLocalConfigStore", "software", "valve", "steam", "apps")
        apps["1"] = {"LaunchOptions": "x"}
        self.assertIn("1", d["UserLocalConfigStore"]["Software"]["Valve"]["Steam"]["apps"])
        new = vdf.ensure(d, "UserLocalConfigStore", "Fresh", "Inner")
        self.assertEqual(new, {})
        self.assertIn("Fresh", d["UserLocalConfigStore"])

    def test_unterminated_raises(self):
        with self.assertRaises(vdf.VDFError):
            vdf.loads('"a"\n{\n"b" "c"\n')


if __name__ == "__main__":
    unittest.main()
