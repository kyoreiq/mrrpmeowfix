import gzip
import io
import json
import tempfile
import unittest
from pathlib import Path

from mrrpmeowfix import index
from mrrpmeowfix.knowledge import NEVER, NORMAL, RISKY, load
from mrrpmeowfix.launchopts import sanitize

DAY = 86400
NOW = 1_800_000_000


def report(appid, title, gpu, verdict="yes", variant="official", ge=None, opts=None, notes=None, age_days=10):
    r = {"verdict": verdict, "variant": variant}
    if ge:
        r["customProtonVersion"] = ge
    if opts:
        r["launchOptions"] = opts
    if notes:
        r["notes"] = {"extra": notes}
    return {
        "app": {"steam": {"appId": str(appid)}, "title": title},
        "responses": r,
        "timestamp": NOW - age_days * DAY,
        "systemInfo": {"gpu": gpu},
    }


FIXTURE = [
    report(10, "Game A", "NVIDIA GeForce RTX 2060 SUPER", variant="ge", ge="GE-Proton10-34",
           opts="PROTON_ENABLE_NVAPI=1 gamemoderun %command%"),
    report(10, "Game A", "NVIDIA GeForce RTX 3070", variant="ge", ge="GE-Proton10-34",
           opts="PROTON_ENABLE_NVAPI=1 %command% -dx11", notes="ran protontricks 10 vcrun2019"),
    report(10, "Game A", "NVIDIA GeForce GTX 1080", variant="experimental", opts="gamemoderun %command%"),
    report(10, "Game A", "AMD Radeon RX 6800", variant="official", opts="-dx11"),
    report(10, "Game A", "AMD Custom GPU 0405", verdict="no", variant="official", opts="PROTON_LOG=1 %command%"),
    report(10, "Game A", "Intel Arc A770", variant="official", age_days=1000),
    report(20, "Other Thing", "AMD Radeon RX 580", variant="native"),
]


class StreamTests(unittest.TestCase):
    def test_reads_all_objects_across_chunks(self):
        text = json.dumps(FIXTURE, indent=2)
        got = list(index.iter_reports(io.StringIO(text), chunk=37))
        self.assertEqual(got, FIXTURE)

    def test_empty_array(self):
        self.assertEqual(list(index.iter_reports(io.StringIO("[ ]"))), [])

    def test_truncated_raises(self):
        with self.assertRaises(ValueError):
            list(index.iter_reports(io.StringIO(json.dumps(FIXTURE)[:-40]), chunk=50))


class DistillTests(unittest.TestCase):
    def setUp(self):
        self.d = index.distill(FIXTURE, now=NOW)

    def test_gpu_bucket(self):
        self.assertEqual(index.gpu_vendor("NVIDIA GeForce RTX 2060 SUPER"), "nvidia")
        self.assertEqual(index.gpu_vendor("AMD Custom GPU 0405"), "amd")
        self.assertEqual(index.gpu_vendor("Mesa Intel(R) UHD 620"), "intel")
        self.assertEqual(index.gpu_vendor("llvmpipe"), "other")

    def test_counts(self):
        game = self.d["games"]["10"]
        self.assertEqual(game["t"], "Game A")
        nv = game["b"]["nvidia"]
        self.assertEqual((nv["n"], nv["g"]), (3, 3))
        self.assertEqual(nv["v"], {"ge": 2, "experimental": 1})
        self.assertEqual(nv["ge"], {"GE-Proton10-34": 2})
        self.assertEqual(nv["lo"]["PROTON_ENABLE_NVAPI=1"], 2)
        self.assertEqual(nv["lo"]["gamemoderun"], 2)
        self.assertEqual(nv["vb"], {"vcrun2019": 1})

    def test_bad_reports_dont_count_tokens(self):
        amd = self.d["games"]["10"]["b"]["amd"]
        self.assertEqual((amd["n"], amd["g"]), (2, 1))
        self.assertNotIn("PROTON_LOG=1", amd["lo"])

    def test_window_falls_back_to_all(self):
        intel = self.d["games"]["10"]["b"]["intel"]
        self.assertEqual(intel["n"], 1)
        self.assertEqual(intel["w"], "all")
        allb = self.d["games"]["10"]["b"]["all"]
        self.assertEqual(allb["w"], "recent")
        self.assertEqual(allb["n"], 5)

    def test_save_load_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "i.json.gz"
            index.save(self.d, p)
            with gzip.open(p, "rt") as f:
                self.assertEqual(json.load(f)["games"]["20"]["t"], "Other Thing")
            idx = index.Index.from_file(p)
            stats = idx.get(10)
            self.assertEqual(stats.title, "Game A")
            name, bucket = stats.bucket("nvidia")
            self.assertEqual(name, "all")  # only 3 good NVIDIA reports, under the 5 minimum
            self.assertIsNone(idx.get(999))
            self.assertEqual([s.appid for s in idx.search("other")], [20])

    def test_newest_dump_name(self):
        names = ["reports_sep1_2026.tar.gz", "reports_nov1_2026.tar.gz", "reports_dec1_2025.tar.gz", "README.md"]
        self.assertEqual(index.newest_dump(names), "reports_nov1_2026.tar.gz")


class KnowledgeTests(unittest.TestCase):
    def test_levels(self):
        k = load()
        self.assertEqual(k.classify(sanitize("gamemoderun"), "nvidia", False, False).level, NORMAL)
        self.assertEqual(k.classify(sanitize("gamemoderun"), "nvidia", True, False).level, NORMAL)
        self.assertEqual(k.classify(sanitize("PROTON_ENABLE_NVAPI=1"), "amd", False, False).level, NEVER)
        self.assertEqual(k.classify(sanitize("PROTON_ENABLE_NVAPI=1"), "nvidia", True, False).level, RISKY)
        self.assertEqual(k.classify(sanitize("PROTON_LOG=1"), "nvidia", False, False).level, NEVER)
        self.assertEqual(k.classify(sanitize("PROTON_USE_WINED3D=1"), "nvidia", False, False).level, RISKY)
        self.assertEqual(k.classify(sanitize("SOME_UNKNOWN=1"), "nvidia", False, False).level, RISKY)
        self.assertEqual(k.classify(sanitize("prime-run"), "nvidia", False, False).level, NEVER)
        self.assertEqual(k.classify(sanitize("prime-run"), "nvidia", False, True).level, NORMAL)
        self.assertEqual(k.classify(sanitize("mangohud"), "nvidia", False, False).level, NEVER)


if __name__ == "__main__":
    unittest.main()
