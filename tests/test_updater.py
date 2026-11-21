import hashlib
import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from mrrpmeowfix import updater


def build_zip(version: str, extra: dict[str, str] | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mrrpmeowfix/mrrpmeowfix/__init__.py", f'VERSION = "{version}"\n')
        z.writestr("mrrpmeowfix/mrrpmeowfix/core.py", "x = 1\n")
        z.writestr("mrrpmeowfix/data/fixes.json", "{}")
        z.writestr("mrrpmeowfix/install.sh", "echo hi")
        for name, text in (extra or {}).items():
            z.writestr(name, text)
    return buf.getvalue()


def release(version="1.2.0"):
    return {"tag_name": f"v{version}", "body": "Faster scans.", "assets": [
        {"name": f"mrrpmeowfix-{version}.zip", "browser_download_url": "zip-url", "size": 10},
        {"name": f"mrrpmeowfix-{version}.zip.sha256", "browser_download_url": "sha-url", "size": 1},
    ]}


class VersionTests(unittest.TestCase):
    def test_compare(self):
        self.assertTrue(updater.newer("v1.2.0", "1.1.9"))
        self.assertTrue(updater.newer("1.10.0", "1.9.0"))
        self.assertFalse(updater.newer("1.1.0", "1.1.0"))
        self.assertFalse(updater.newer("junk", "1.0.0"))

    def test_parse_release(self):
        rel = updater.parse_release(release())
        self.assertEqual((rel.version, rel.zip_url, rel.sha_url, rel.notes), ("1.2.0", "zip-url", "sha-url", "Faster scans."))
        self.assertIsNone(updater.parse_release({"tag_name": "v1.2.0", "assets": []}))


class LatestTests(unittest.TestCase):
    def test_latest(self):
        import json
        seen = []
        rel = updater.latest({"repo": "someone/mrrpmeowfix"},
                             fetch=lambda url: seen.append(url) or json.dumps(release("1.3.0")).encode())
        self.assertEqual(rel.version, "1.3.0")
        self.assertEqual(seen, ["https://api.github.com/repos/someone/mrrpmeowfix/releases/latest"])
        self.assertIsNone(updater.latest({"repo": ""}, fetch=lambda url: self.fail("fetched")))


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.app = base / "mrrpmeowfix/app"
        (self.app / "mrrpmeowfix").mkdir(parents=True)
        (self.app / "mrrpmeowfix/__init__.py").write_text('VERSION = "1.1.0"\n')
        self.cache = base / "cache"
        self.cache.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def fetcher(self, payload: bytes, sha: str | None = None):
        digest = sha or hashlib.sha256(payload).hexdigest()

        def fetch(url):
            return payload if url == "zip-url" else f"{digest}  mrrpmeowfix-1.2.0.zip\n".encode()
        return fetch

    def test_installs_and_keeps_old(self):
        payload = build_zip("1.2.0")
        rel = updater.parse_release(release())
        v = updater.install(rel, app_dir=self.app, cache=self.cache, fetch=self.fetcher(payload))
        self.assertEqual(v, "1.2.0")
        self.assertIn('"1.2.0"', (self.app / "mrrpmeowfix/__init__.py").read_text())
        self.assertTrue((self.app / "data/fixes.json").exists())
        self.assertFalse((self.app / "install.sh").exists())
        self.assertIn('"1.1.0"', (self.app.parent / "app.old/mrrpmeowfix/__init__.py").read_text())
        updater.cleanup_old(self.app)
        self.assertFalse((self.app.parent / "app.old").exists())

    def test_bad_checksum_changes_nothing(self):
        rel = updater.parse_release(release())
        with self.assertRaises(ValueError):
            updater.install(rel, app_dir=self.app, cache=self.cache, fetch=self.fetcher(build_zip("1.2.0"), "0" * 64))
        self.assertIn('"1.1.0"', (self.app / "mrrpmeowfix/__init__.py").read_text())
        self.assertFalse((self.app.parent / "app.new").exists())

    def test_wrong_version_inside_changes_nothing(self):
        rel = updater.parse_release(release())
        with self.assertRaises(ValueError):
            updater.install(rel, app_dir=self.app, cache=self.cache, fetch=self.fetcher(build_zip("9.9.9")))
        self.assertIn('"1.1.0"', (self.app / "mrrpmeowfix/__init__.py").read_text())

    def test_rejects_path_escape(self):
        rel = updater.parse_release(release())
        payload = build_zip("1.2.0", {"mrrpmeowfix/data/../../../evil.txt": "x"})
        with self.assertRaises(ValueError):
            updater.install(rel, app_dir=self.app, cache=self.cache, fetch=self.fetcher(payload))
        self.assertFalse((Path(self.tmp.name) / "evil.txt").exists())


if __name__ == "__main__":
    unittest.main()
