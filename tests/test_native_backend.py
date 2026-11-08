"""Reversible delivery tests use tiny compiled inert programs, never Unity."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from unity_scale import core, native_backend as backend, native_launch


class NativeDeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which('cc') or not shutil.which('pkg-config'):
            raise unittest.SkipTest('Native compiler/pkg-config unavailable')
        if subprocess.run(['pkg-config', '--exists', 'json-c', 'openssl']).returncode:
            raise unittest.SkipTest('Native json-c/OpenSSL development files unavailable')
        cls.compiled = tempfile.TemporaryDirectory(prefix='unity-exec-fixture-build-')
        build = Path(cls.compiled.name)
        source = build / 'original.c'
        source.write_text('''#include <json-c/json.h>
#include <stdlib.h>
#include <stdio.h>
int main(int n,char **v){struct json_object*r=json_object_new_object(),*a=json_object_new_array();for(int i=0;i<n;i++)json_object_array_add(a,json_object_new_string(v[i]));json_object_object_add(r,"argv",a);const char*k[]={"GDK_SCALE","GDK_DPI_SCALE","GDK_BACKEND","LD_PRELOAD","UNITY_EDITOR_SCALING_PUBLIC_EDITOR","UNITY_EDITOR_SCALING_SETTINGS","UNITY_EDITOR_SCALING_HOST_ENV","UNITY_NATIVE_STARTUP_PERCENT"};for(unsigned i=0;i<sizeof k/sizeof*k;i++){const char*x=getenv(k[i]);json_object_object_add(r,k[i],x?json_object_new_string(x):NULL);}puts(json_object_to_json_string(r));json_object_put(r);return 0;}''')
        subprocess.run(['cc', str(source), '-ljson-c', '-o', str(build / 'original')], check=True, capture_output=True)
        empty = build / 'empty.c'
        empty.write_text('int neutral_test_fixture;')
        subprocess.run(['cc', '-shared', '-fPIC', str(empty), '-o', str(build / 'neutral.so')], check=True, capture_output=True)
        cls.original_bytes = (build / 'original').read_bytes()
        cls.library_bytes = (build / 'neutral.so').read_bytes()

    @classmethod
    def tearDownClass(cls):
        cls.compiled.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='unity-native-delivery-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.public = self.root / '6000.3.27f2/Editor/Unity'
        self.public.parent.mkdir(parents=True)
        self.public.write_bytes(self.original_bytes)
        self.public.chmod(0o755)
        (self.public.parent / 'Data/Managed').mkdir(parents=True)
        (self.public.parent / 'Data/Managed/UnityEditor.dll').write_bytes(b'inert fixture')
        (self.public.parent / 'Data/Resources').mkdir()
        self.library = self.root / 'neutral.so'
        self.library.write_bytes(self.library_bytes)
        self.source_sha = backend.digest(self.public)
        self.addCleanup(patch.stopall)
        patch.object(backend, 'SUPPORTED_ELF_SHA256', self.source_sha).start()
        patch.object(native_launch, 'SUPPORTED_ELF_SHA256', self.source_sha).start()
        self.store = core.Store(self.root / 'settings')
        self.store.set_profile(self.public, self.store.get_profile(self.public))
        public, backup, package = backend.paths(self.public)
        receipt = dict(constructor_contract='product-profile-v1', host_environment_abi=1, restore_host_on_refusal=True,
                       original_sha256=self.source_sha, public_editor=str(public), target_exe=str(backup), settings_path=str(self.store.path),
                       library=str(self.library), library_sha256=backend.digest(self.library), runtime_verified_percentages=[])
        self.manifest = self.root / 'native-manifest.json'
        self.manifest.write_text(json.dumps(receipt))
        self.stage = self.root / 'prepared'
        backend.prepare(self.public, self.store.path, self.manifest, backend.digest(self.manifest), self.stage)
        self.preparation_pin = backend.digest(self.stage / 'receipt.json')
        self.initial_identity = backend._identity(self.public)

    def install(self):
        return backend.install(self.stage, self.preparation_pin)

    def test_prepare_does_not_change_editor_then_install_discover_restore_exact_bytes(self):
        self.assertEqual(self.public.read_bytes(), self.original_bytes)
        self.assertFalse((self.public.parent / backend.BACKUP_NAME).exists())
        status = self.install()
        self.assertTrue(status['connected'])
        found = core.inspect_editor(self.public)
        self.assertEqual(found.path, str(self.public))
        original = backend.verified_original(self.public)
        self.assertEqual(original.read_bytes(), self.original_bytes)
        self.assertEqual(backend._identity(original), self.initial_identity)
        self.assertEqual(original.parent / 'Data', self.public.parent / 'Data')
        restored = backend.restore(self.public)
        self.assertTrue(restored['restored'])
        self.assertEqual(self.public.read_bytes(), self.original_bytes)
        self.assertEqual(backend._identity(self.public), self.initial_identity)
        self.assertFalse((self.public.parent / backend.PACKAGE_NAME).exists())

    def test_compiled_launcher_preserves_full_argv_including_argv0_and_host_policy(self):
        self.install()
        env = dict(os.environ, GDK_SCALE='2', GDK_DPI_SCALE='0.725', GDK_BACKEND='wayland,x11')
        for key in ('LD_PRELOAD', native_launch.HOST_KEY):
            env.pop(key, None)
        arguments = ['custom original argv0', '-projectPath', '/tmp/space and $(literal)', '--opaque']
        run = subprocess.run(arguments, executable=self.public, env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(run.returncode, 0, run.stderr)
        out = json.loads(run.stdout)
        self.assertEqual(out['argv'], arguments)
        self.assertEqual(out['GDK_SCALE'], '2')  # The neutral fixture performs no native GTK writes.
        self.assertEqual(out['GDK_DPI_SCALE'], '0.725')
        self.assertIsNone(out['UNITY_NATIVE_STARTUP_PERCENT'])
        self.assertEqual(out[native_launch.EDITOR_KEY], str(self.public))
        self.assertEqual(out[native_launch.SETTINGS_KEY], str(self.store.path))
        self.assertEqual(json.loads(out[native_launch.HOST_KEY]), dict(abi=1,GDK_SCALE='2',GDK_DPI_SCALE='0.725',GDK_BACKEND='wayland,x11'))

    def test_helper_restores_parent_host_and_removes_owned_preload_without_loading_dso(self):
        self.install()
        library = self.public.parent / backend.PACKAGE_NAME / 'native.so'
        env = dict(os.environ, GDK_SCALE='1', GDK_DPI_SCALE='1', GDK_BACKEND='x11', LD_PRELOAD=str(library))
        env[native_launch.HOST_KEY] = json.dumps(dict(abi=1,GDK_SCALE=None,GDK_DPI_SCALE='',GDK_BACKEND='wayland,x11'))
        run = subprocess.run([str(self.public), '-batchMode'], env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(run.returncode, 0, run.stderr)
        out = json.loads(run.stdout)
        self.assertIsNone(out['GDK_SCALE'])
        self.assertEqual(out['GDK_DPI_SCALE'], '')
        self.assertEqual(out['GDK_BACKEND'], 'wayland,x11')
        self.assertIsNone(out['LD_PRELOAD'])

    def test_original_or_preparation_mutation_refuses_without_install(self):
        (self.stage / 'wrapper').write_bytes(b'changed')
        with self.assertRaises(ValueError):
            self.install()
        self.assertEqual(self.public.read_bytes(), self.original_bytes)
        self.assertFalse((self.public.parent / backend.BACKUP_NAME).exists())

    def test_foreign_public_update_is_not_overwritten_on_restore_or_discovery(self):
        self.install()
        self.public.write_bytes(b'foreign update')
        with self.assertRaises(ValueError):
            backend.restore(self.public)
        with self.assertRaises(core.AppError):
            core.inspect_editor(self.public)
        self.assertEqual(self.public.read_bytes(), b'foreign update')
        self.assertTrue((self.public.parent / backend.BACKUP_NAME).exists())

    def test_crash_after_wrapper_promotion_can_restore_from_prepared_journal(self):
        self.install()
        receipt = self.public.parent / backend.PACKAGE_NAME / 'receipt.json'
        value = json.loads(receipt.read_text())
        value['state'] = 'prepared'
        backend.atomic_json(receipt, value)
        backend.restore(self.public)
        self.assertEqual(self.public.read_bytes(), self.original_bytes)

    def test_settings_manifest_mismatch_refuses_before_staging(self):
        manifest = json.loads(self.manifest.read_text())
        manifest['settings_path'] = str(self.root / 'another-settings.json')
        self.manifest.write_text(json.dumps(manifest))
        target = self.root / 'must-not-be-created'
        with self.assertRaises(ValueError):
            backend.prepare(self.public, self.store.path, self.manifest, backend.digest(self.manifest), target)
        self.assertFalse(target.exists())
        self.assertEqual(self.public.read_bytes(), self.original_bytes)

    def test_connected_status_requires_the_same_app_settings_document(self):
        self.install()
        profile = self.store.get_profile(self.public)
        self.assertTrue(backend.status(self.public, profile, settings_path=self.store.path)['connected'])
        mismatched = backend.status(self.public, profile, settings_path=self.root / 'other.json')
        self.assertFalse(mismatched['connected'])
        self.assertIsNone(mismatched['current_scale'])

    def test_injected_commit_failure_rolls_back_original(self):
        real = backend.atomic_json
        def fail(path, value):
            if value.get('state') == 'installed':
                raise OSError('injected receipt failure')
            return real(path, value)
        with patch.object(backend, 'atomic_json', side_effect=fail):
            with self.assertRaises(OSError):
                self.install()
        self.assertEqual(self.public.read_bytes(), self.original_bytes)
        self.assertFalse((self.public.parent / backend.PACKAGE_NAME).exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
