import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from unity_scale import core


class Settings:
    def __init__(self, paths=()):
        self.paths = list(map(str, paths))
        self.reads = 0

    def load(self):
        self.reads += 1
        return {"extra_editors": self.paths}


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="unity-discovery-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.config = self.home / ".config"
        self.addCleanup(patch.stopall)
        patch.object(Path, "home", return_value=self.home).start()
        patch.dict("os.environ", {"XDG_CONFIG_HOME": str(self.config)}).start()
        # Discovery tests inspect only their fixture installations, including
        # on development machines with Editors under /opt.
        original_glob = Path.glob
        patch.object(Path, "glob", lambda path, pattern: original_glob(path, pattern)
                     if path.is_relative_to(self.root) else iter(())).start()

    def editor(self, installation, *, version=None):
        executable = installation / "Editor/Unity"
        executable.parent.mkdir(parents=True)
        header = bytearray(64)
        header[:7] = b"\x7fELF\x02\x01\x01"
        header[16:18] = (3).to_bytes(2, "little")
        executable.write_bytes(header)
        executable.chmod(0o755)
        data = executable.parent / "Data"
        (data / "Managed").mkdir(parents=True)
        (data / "Managed/UnityEditor.dll").write_bytes(b"fixture")
        (data / "Resources").mkdir()
        if version:
            (executable.parent / "UnityVersion.txt").write_text(version)
        return executable

    def test_installed_elf_discovery_has_no_native_adapter_dependency(self):
        path = self.editor(self.root / "6000.3.27f2")
        with patch.dict("sys.modules", {"unity_scale.native_control": None}):
            direct = core.inspect_editor(path)
            folder = core.inspect_editor(path.parent.parent)
        self.assertEqual(direct, folder)
        self.assertEqual(direct.path, str(path.resolve()))
        self.assertEqual(direct.version, "6000.3.27f2")

    def test_metadata_version_and_unknown_unversioned_installation(self):
        known = self.editor(self.root / "named-install", version="6000.3.27f2\n")
        unknown = self.editor(self.root / "6000.3.27f2" / "unversioned")
        self.assertEqual(core.inspect_editor(known).version, "6000.3.27f2")
        # A distant directory name does not establish this installation's version.
        self.assertEqual(core.inspect_editor(unknown).version, "Unknown version")

    def test_old_wrapper_is_rejected_without_running_it(self):
        path = self.editor(self.root / "wrapper")
        sentinel = self.root / "EXECUTED"
        path.write_text(f"#!/bin/sh\n# UNITY_SCALE_MANAGED_WRAPPER\ntouch '{sentinel}'\n")
        with self.assertRaises(core.AppError):
            core.inspect_editor(path)
        self.assertFalse(sentinel.exists())

    def test_bad_elf_and_incomplete_installation_are_rejected(self):
        path = self.editor(self.root / "bad")
        path.write_bytes(b"\x7fELF")
        with self.assertRaises(core.AppError):
            core.inspect_editor(path)
        other = self.editor(self.root / "incomplete")
        (other.parent / "Data/Managed/UnityEditor.dll").unlink()
        with self.assertRaises(core.AppError):
            core.inspect_editor(other)

    def test_active_store_and_resolved_dedup_preserve_distinct_same_version_installs(self):
        first = self.editor(self.root / "one/6000.3.27f2")
        second = self.editor(self.root / "two/6000.3.27f2")
        alias = self.root / "alias"
        alias.symlink_to(first.parent.parent, target_is_directory=True)
        store = Settings([first, alias, second])
        with patch.object(core, "Store", side_effect=AssertionError("wrong settings store")):
            found = core.discover_editors([first, first.parent.parent], store=store)
        self.assertEqual({row.path for row in found}, {str(first), str(second)})
        self.assertEqual(store.reads, 1)

    def test_hub_scan_orders_versions_and_uses_directory_containment_for_source(self):
        hub = self.root / "hub"
        older = self.editor(hub / "6000.2.1f1")
        newer = self.editor(hub / "6000.3.27f2")
        outside = self.editor(self.root / "hub-other/6000.3.27f2")
        settings = self.config / "UnityHub/settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({"installPath": str(hub)}))
        found = core.discover_editors(store=Settings([outside]))
        by_path = {row.path: row for row in found}
        self.assertEqual(set(by_path), {str(older), str(newer), str(outside)})
        self.assertEqual(by_path[str(newer)].source, "Unity Hub")
        self.assertEqual(by_path[str(outside)].source, "Located Editor")
        self.assertEqual(found[-1].path, str(older))

    def test_marked_and_app_owned_experiments_stay_excluded(self):
        lab = self.root / "experiment"
        marked = self.editor(lab / "copy")
        (lab / ".scaling-lab-disposable").write_text("disposable\n")
        owned = self.editor(self.root / "app-files/copied-editor")
        legitimate = self.editor(self.root / "user-install")
        with patch.object(core, "ROOT", self.root / "app-files"):
            for path in (marked, owned):
                with self.assertRaises(core.AppError):
                    core.inspect_editor(path)
            found = core.discover_editors(store=Settings([marked, owned, legitimate]), include_lab=True)
        self.assertEqual([row.path for row in found], [str(legitimate)])

    def test_diagnostics_claim_settings_only_and_current_scale_stays_unknown(self):
        report = core.diagnostics()
        self.assertEqual(core.APP_ID, "io.github.unityscale.UnityScale")
        self.assertEqual(set(report["capabilities"]), {"settings_manager", "native_startup"})
        self.assertTrue(report["capabilities"]["native_startup"]["restart_required"])
        self.assertFalse(report["live_apply"])
        self.assertFalse(report["capabilities"]["settings_manager"]["saving_applies_scale"])
        self.assertIsNone(report["current_scale"])
        self.assertIsNone(core.get_running_scale("/some/Unity"))
        self.assertNotIn("V4", json.dumps(report))
        self.assertNotIn("adapter", json.dumps(report).lower())


if __name__ == "__main__":
    unittest.main()
