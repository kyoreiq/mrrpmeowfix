import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mrrpmeowfix import fixlist


class FixListTests(unittest.TestCase):
    def test_clean_drops_bad_entries(self):
        raw = {"version": 1, "games": {
            "2406770": {"name": "Bodycam", "add": ["-dx11", 5], "block": "x", "proton": "ge", "note": "hi"},
            "abc": {"add": ["-x"]},
            "10": "nope",
            "20": {"proton": "something-else", "note": "x" * 600},
        }}
        games = fixlist.clean(raw)
        self.assertEqual(games["2406770"], {"add": ["-dx11"], "block": [], "proton": "ge", "note": "hi"})
        self.assertNotIn("abc", games)
        self.assertNotIn("10", games)
        self.assertIsNone(games["20"]["proton"])
        self.assertLessEqual(len(games["20"]["note"]), 300)

    def test_raw_url(self):
        self.assertEqual(fixlist.raw_url({"repo": "someone/mrrpmeowfix", "branch": "main"}),
                         "https://raw.githubusercontent.com/someone/mrrpmeowfix/main/fixes/community.json")
        self.assertIsNone(fixlist.raw_url({"repo": ""}))
        self.assertIsNone(fixlist.raw_url({"repo": "bad repo/../x"}))

    def test_refresh_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "community.json"
            payload = json.dumps({"version": 1, "games": {"730": {"add": ["-vulkan"]}}}).encode()
            with mock.patch.object(fixlist, "_cache", return_value=cache), \
                 mock.patch.object(fixlist, "_fetch", return_value=payload):
                self.assertTrue(fixlist.refresh({"repo": "someone/mrrpmeowfix", "branch": "main"}, force=True))
                self.assertEqual(fixlist.load().get(730)["add"], ["-vulkan"])
                self.assertFalse(fixlist.refresh({"repo": "someone/mrrpmeowfix", "branch": "main"}))  # fresh cache
            fixlist.load.cache_clear()

    def test_no_repo_means_no_fetch(self):
        with mock.patch.object(fixlist, "_fetch") as fetch:
            self.assertFalse(fixlist.refresh({"repo": ""}, force=True))
            fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
