import io
import tarfile
import tempfile
import unittest
from pathlib import Path

from mrrpmeowfix import protonge, system


class SystemTests(unittest.TestCase):
    def test_os_release(self):
        info = system.parse_os_release('PRETTY_NAME="CachyOS"\nID=cachyos\nID_LIKE=arch\n')
        self.assertEqual(info, {"PRETTY_NAME": "CachyOS", "ID": "cachyos", "ID_LIKE": "arch"})
        self.assertEqual(system.package_manager(info, which=lambda _: None), "pacman")
        self.assertEqual(system.package_manager({"ID": "linuxmint", "ID_LIKE": "ubuntu debian"}, which=lambda _: None), "apt")
        self.assertEqual(system.package_manager({"ID": "fedora"}, which=lambda _: None), "dnf")
        self.assertEqual(system.package_manager({"ID": "opensuse-tumbleweed", "ID_LIKE": "opensuse suse"},
                                                which=lambda _: None), "zypper")
        self.assertEqual(system.package_manager({"ID": "weird"}, which=lambda c: "/usr/bin/apt" if c == "apt" else None), "apt")
        self.assertIsNone(system.package_manager({"ID": "weird"}, which=lambda _: None))

    def test_install_commands(self):
        self.assertEqual(system.install_command("pacman", "gamemode"), "sudo pacman -S --needed gamemode lib32-gamemode")
        self.assertEqual(system.install_command("apt", "gamemode"), "sudo apt install gamemode")
        self.assertEqual(system.install_command("dnf", "mangohud"), "sudo dnf install mangohud mangohud.i686")
        self.assertIn("flatpak install", system.install_command(None, "protontricks"))
        self.assertEqual(system.install_command("pacman", "vulkan32", gpu="amd"), "sudo pacman -S --needed lib32-vulkan-radeon")

    def test_multilib(self):
        self.assertTrue(system.multilib_enabled("[options]\n[multilib]\nInclude = /etc/pacman.d/mirrorlist\n"))
        self.assertFalse(system.multilib_enabled("[options]\n#[multilib]\n#Include = /etc/pacman.d/mirrorlist\n"))
        self.assertFalse(system.multilib_enabled(""))

    def test_terminal_command(self):
        cmd = system.terminal_command("echo hi", which=lambda c: "/usr/bin/kitty" if c == "kitty" else None, env={})
        self.assertEqual(cmd[0], "kitty")
        self.assertIn("echo hi", cmd[-1])
        self.assertIsNone(system.terminal_command("x", which=lambda _: None, env={}))

    def test_vendor_ids(self):
        self.assertEqual(system.VENDORS["0x10de"], "nvidia")
        self.assertEqual(system.VENDORS["0x1002"], "amd")


class ProtonGeTests(unittest.TestCase):
    def make_tar(self, names):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            for name in names:
                data = b"x"
                ti = tarfile.TarInfo(name)
                ti.size = len(data)
                tar.addfile(ti, io.BytesIO(data))
        return buf.getvalue()

    def test_safe_extract(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            good = tmp / "good.tar.gz"
            good.write_bytes(self.make_tar(["GE-Proton11-12/proton", "GE-Proton11-12/compatibilitytool.vdf"]))
            out = tmp / "compat"
            self.assertEqual(protonge.extract(good, out), "GE-Proton11-12")
            self.assertTrue((out / "GE-Proton11-12/proton").exists())

            bad = tmp / "bad.tar.gz"
            bad.write_bytes(self.make_tar(["GE-Proton11-12/../../evil"]))
            with self.assertRaises(ValueError):
                protonge.extract(bad, tmp / "compat2")
            self.assertFalse((tmp / "evil").exists())

    def test_pick_asset(self):
        release = {"tag_name": "GE-Proton11-12", "assets": [
            {"name": "GE-Proton11-12.sha512sum", "browser_download_url": "u1", "size": 1},
            {"name": "GE-Proton11-12.tar.gz", "browser_download_url": "u2", "size": 500},
        ]}
        rel = protonge.parse_release(release)
        self.assertEqual((rel.tag, rel.url, rel.size, rel.sha_url), ("GE-Proton11-12", "u2", 500, "u1"))


if __name__ == "__main__":
    unittest.main()
