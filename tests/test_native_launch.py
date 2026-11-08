"""Offline neutral-loader policy tests; inert files are never executed/loaded."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from unity_scale import core, native_launch as launch


class NativeLaunchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='unity-native-planning-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.public = self.root / 'Unity'
        self.public.write_bytes(b'inert original fixture; never executed')
        self.public.chmod(0o700)
        self.library = self.root / 'native.so'
        self.library.write_bytes(b'inert native fixture; never loaded')
        self.store = core.Store(self.root / 'settings')
        self.manifest = self.root / 'manifest.json'
        self.expected = launch.digest(self.public)
        self.receipt = dict(constructor_contract='product-profile-v1', host_environment_abi=1,
                            restore_host_on_refusal=True, original_sha256=self.expected,
                            public_editor=str(self.public), target_exe=str(self.public), library=str(self.library),
                            settings_path=str(self.store.path), library_sha256=launch.digest(self.library))
        self.addCleanup(patch.stopall)
        patch.object(launch, 'SUPPORTED_ELF_SHA256', self.expected).start()
        self.pin()
        self.argv = ['literal custom argv0', '-projectPath', '/path with spaces/$(literal)']
        self.host = dict(GDK_SCALE='2', GDK_DPI_SCALE='0.725', GDK_BACKEND='wayland,x11', GSK_RENDERER='ngl')

    def pin(self):
        self.manifest.write_text(json.dumps(self.receipt))
        self.sha = launch.digest(self.manifest)

    def plan(self, inherited=None, **kwargs):
        return launch.plan_launch(self.store, self.public, self.argv, self.host if inherited is None else inherited,
                                  manifest=self.manifest, manifest_sha256=self.sha, **kwargs)

    def test_neutral_preload_never_duplicates_settings_factor_or_changes_gdk_renderer(self):
        with patch.object(self.store, 'get_profile', side_effect=AssertionError('constructor alone reads choice')):
            result = self.plan()
        self.assertEqual(result.argv, tuple(self.argv))
        for key, value in self.host.items():
            self.assertEqual(result.environment[key], value)
        self.assertEqual(result.environment['LD_PRELOAD'], str(self.library))
        self.assertEqual(result.environment[launch.SETTINGS_KEY], str(self.store.path))
        self.assertNotIn('UNITY_NATIVE_STARTUP_MODE', result.environment)
        self.assertNotIn('UNITY_NATIVE_STARTUP_PERCENT', result.environment)

    def test_child_restores_original_host_and_keeps_exactly_one_neutral_preload(self):
        first = self.plan()
        inherited = dict(first.environment, GDK_SCALE='1', GDK_DPI_SCALE='1', GDK_BACKEND='x11')
        second = self.plan(inherited)
        self.assertEqual(second.environment['LD_PRELOAD'], str(self.library))
        for key, value in self.host.items():
            self.assertEqual(second.environment[key], value)

    def test_presence_and_empty_host_values_roundtrip(self):
        host = {'GDK_SCALE': '', 'GDK_BACKEND': 'wayland,x11'}
        result = self.plan(host)
        changed = dict(result.environment, GDK_DPI_SCALE='1', GDK_SCALE='1')
        restored = launch.restore_host_environment(changed)
        self.assertEqual(restored['GDK_SCALE'], '')
        self.assertNotIn('GDK_DPI_SCALE', restored)

    def test_foreign_preload_order_is_preserved_and_owned_alias_is_removed(self):
        alias = self.root / 'alias.so'
        alias.symlink_to(self.library)
        host = dict(self.host, LD_PRELOAD=f'/foreign/a.so:{alias}:/foreign/b.so:{self.library}')
        result = self.plan(host)
        self.assertEqual(result.environment['LD_PRELOAD'], f'{self.library}:/foreign/a.so:/foreign/b.so')
        # Native constructor, not the planner, must refuse CUSTOM with foreign
        # preloads before native mutation. This neutral plan claims no apply.
        self.assertIn('No current-scale', result.note)

    def test_helper_bypasses_preload_and_restores_host_without_profile_read(self):
        inherited = dict(self.plan().environment, GDK_SCALE='1')
        self.argv.append('-batchMode')
        result = self.plan(inherited)
        self.assertEqual(result.mode, 'helper-bypass')
        self.assertNotIn('LD_PRELOAD', result.environment)
        self.assertEqual(result.environment['GDK_SCALE'], '2')

    def test_bad_environment_envelope_is_rejected_without_mutating_input(self):
        for raw in ('{}', '{"abi":1,"abi":1}', 'null', 'not json'):
            inherited = dict(self.host, **{launch.HOST_KEY: raw})
            original = dict(inherited)
            with self.assertRaises(ValueError):
                self.plan(inherited)
            self.assertEqual(inherited, original)

    def test_settings_binding_and_manifest_or_library_tamper_refuse(self):
        self.receipt['settings_path'] = '/wrong/settings.json'
        self.pin()
        with self.assertRaisesRegex(ValueError, 'settings path'):
            self.plan()
        self.receipt['settings_path'] = str(self.store.path)
        self.pin()
        self.library.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            self.plan()
        self.manifest.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'identity'):
            self.plan()

    def test_whitespace_library_requires_explicit_same_inode_loader_alias(self):
        folder = self.root / 'spaces here'
        folder.mkdir()
        self.library = self.library.rename(folder / 'native.so')
        self.receipt['library'] = str(self.library)
        self.pin()
        with self.assertRaisesRegex(ValueError, 'whitespace'):
            self.plan()
        alias = self.root / 'loader.so'
        alias.symlink_to(self.library)
        self.assertEqual(self.plan(preload_alias=alias).environment['LD_PRELOAD'], str(alias))


if __name__ == '__main__':
    unittest.main(verbosity=2)
