"""AppImage migration fixtures never launch GTK, Unity, or modify user paths."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from unity_scale import core, native_backend as backend, user_install
from unity_scale.private_store import Store, atomic_json


class UserInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='unity-appimage-install-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'isolated')
        self.public = self.root / '6000.3.27f2/Editor/Unity'
        self.public.parent.mkdir(parents=True)
        self.original = b'\x7fELF' + b'inert original fixture' * 10
        self.public.write_bytes(self.original)
        self.public.chmod(0o755)
        (self.public.parent / 'Data/Managed').mkdir(parents=True)
        (self.public.parent / 'Data/Managed/UnityEditor.dll').write_bytes(b'fixture')
        (self.public.parent / 'Data/Resources').mkdir()
        self.sha = backend.digest(self.public)
        self.addCleanup(patch.stopall)
        patch.object(backend, 'SUPPORTED_ELF_SHA256', self.sha).start()
        self.bundle = self.root / 'prebuilt'
        self.bundle.mkdir()
        (self.bundle / 'wrapper-v2').write_bytes(b'\x7fELF inert v2 wrapper')
        (self.bundle / 'native-v2.so').write_bytes(b'\x7fELF inert v2 native')
        atomic_json(self.bundle / 'manifest.json', dict(schema=2, constructor_contract='product-profile-v2',
            original_sha256=self.sha, files={p.name: backend.digest(p) for p in self.bundle.iterdir()}))
        self.image = self.root / 'Downloads/application.AppImage'
        self.image.parent.mkdir()
        self.image.write_bytes(b'\x7fELF' + b'\0' * 4 + b'AI\x02' + b'inert AppImage')
        self.identity = backend._identity(self.public)

    def install(self, image=None):
        return user_install.install_user(image or self.image, store=self.store, bundle=self.bundle,
                                        editors=[self.public], check_running=False)

    def legacy_connection(self):
        public, backup, package = backend.paths(self.public)
        package.mkdir()
        os.link(public, backup)
        wrapper = b'\x7fELF UNITY_EDITOR_SCALING_NATIVE_LAUNCHER_V1 inert old wrapper'
        backend._atomic_bytes(public, wrapper, 0o755)
        (package / 'wrapper').write_bytes(wrapper)
        (package / 'native.so').write_bytes(b'inert old native')
        legacy_settings = user_install._legacy_settings(self.store)
        receipt = dict(schema=1, state='installed', marker=backend.MARKER.decode(), owner_uid=os.getuid(),
            public_editor=str(public), target_exe=str(backup), original_sha256=self.sha,
            original_identity=self.identity, original_mode=0o755, constructor_contract='product-profile-v1',
            host_environment_abi=1, restore_host_on_refusal=True, settings=str(legacy_settings),
            files={name: backend.digest(package / name) for name in ('wrapper', 'native.so')})
        atomic_json(package / 'receipt.json', receipt)
        old_profile = dict(ui_scale_percent=150, follow_desktop=False, render_scale=2,
                           override_enabled=True, control_revision=7)
        atomic_json(legacy_settings, dict(schema_version=2, editors={str(public): old_profile},
            extra_editors=[str(public), '/additional/2022.3.1f1/Editor/Unity']))
        return receipt

    def test_default_paths_use_xdg_and_do_not_write_the_source_tree(self):
        with patch.dict(os.environ, {name: str(self.root / name) for name in
                ('XDG_DATA_HOME', 'XDG_CONFIG_HOME', 'XDG_STATE_HOME')}):
            store = Store()
            self.assertEqual(store.path, self.root / 'XDG_CONFIG_HOME/unity-editor-scaling-for-linux/settings.json')
            self.assertEqual(store.data_dir, self.root / 'XDG_DATA_HOME/unity-editor-scaling-for-linux')
            self.assertEqual(store.state_dir, self.root / 'XDG_STATE_HOME/unity-editor-scaling-for-linux')
            self.assertFalse(store.root.exists())

    def test_fresh_install_uses_prebuilt_and_retains_original_inode(self):
        with patch('subprocess.run', side_effect=AssertionError('user must not compile')):
            result = self.install()
        self.assertEqual(result['connected_editors'], [str(self.public)])
        self.assertEqual(result['version'], core.VERSION)
        original = backend.verified_original(self.public)
        self.assertEqual(backend._identity(original), self.identity)
        self.assertEqual(original.read_bytes(), self.original)
        self.assertEqual(json.loads((self.public.parent / backend.PACKAGE_NAME / 'activation.json').read_text())['settings'], str(self.store.path))
        self.assertEqual((self.store.data_dir / 'application.AppImage').read_bytes(), self.image.read_bytes())
        launcher, desktop, _ = user_install._integration_paths(self.store)
        self.assertIn(str(self.store.data_dir / 'application.AppImage'), launcher.read_text())
        self.assertIn('io.github.unityscale.UnityScale', desktop.name)
        backend.restore(self.public)
        self.assertEqual(backend._identity(self.public), self.identity)

    def _interrupt_promotion(self, point, image=None):
        """A separate process dies without Python finally/exception rollback."""
        pid = os.fork()
        if pid == 0:
            actual_bytes, actual_json = backend._atomic_bytes, user_install.atomic_json
            actual_link = os.link
            def link(source, destination, *args, **kwargs):
                actual_link(source, destination, *args, **kwargs)
                if point == 'original-linked' and Path(destination).name == backend.BACKUP_NAME:
                    os._exit(71)
            def write(path, *args):
                actual_bytes(path, *args)
                if str(path).endswith(point):
                    os._exit(71)
            def write_json(path, *args):
                actual_json(path, *args)
                if str(path).endswith(point) or (point == 'committed-journal' and Path(path).name == 'install-journal.json' and args[0].get('state') == 'installed' and args[0].get('cleanup')):
                    os._exit(71)
            backend._atomic_bytes, user_install.atomic_json = write, write_json
            os.link = link
            self.install(image)
            os._exit(72)
        _, status = os.waitpid(pid, 0)
        self.assertEqual(os.waitstatus_to_exitcode(status), 71)
        self.assertEqual(json.loads((self.store.state_dir / 'install-journal.json').read_text())['state'],
                         'installed' if point == 'committed-journal' else 'prepared')

    def test_power_failure_during_fresh_native_staging_recovers_original(self):
        self._interrupt_promotion('/native-v2.so')
        self.assertTrue(user_install.recover_install(self.store))
        self.assertEqual(self.public.read_bytes(), self.original)
        self.assertEqual(backend._identity(self.public), self.identity)
        self.assertFalse((self.public.parent / backend.BACKUP_NAME).exists())
        self.assertFalse((self.public.parent / backend.PACKAGE_NAME).exists())
        self.assertFalse((self.store.data_dir / 'application.AppImage').exists())
        self.assertFalse(user_install.recover_install(self.store))

    def test_power_failure_after_original_hardlink_leaves_no_orphan_backup(self):
        self._interrupt_promotion('original-linked')
        self.assertTrue(self.public.samefile(self.public.parent / backend.BACKUP_NAME))
        self.assertTrue(user_install.recover_install(self.store))
        self.assertEqual(backend._identity(self.public), self.identity)
        self.assertFalse((self.public.parent / backend.BACKUP_NAME).exists())

    def test_power_failure_after_launcher_swap_recovers_v1_150(self):
        self.legacy_connection()
        old_public = self.public.read_bytes()
        self._interrupt_promotion('/Editor/Unity')
        self.assertTrue(user_install.recover_install(self.store))
        self.assertEqual(self.public.read_bytes(), old_public)
        self.assertEqual(backend._identity(backend.verified_original(self.public)), self.identity)
        self.assertFalse((self.public.parent / backend.PACKAGE_NAME / 'activation.json').exists())
        self.assertEqual(json.loads(user_install._legacy_settings(self.store).read_text())['editors'][str(self.public)]['ui_scale_percent'], 150)

    def test_power_failure_after_receipt_preserves_old_application_and_preferences(self):
        self.install()
        image = self.store.data_dir / 'application.AppImage'
        before_image, before_settings = image.read_bytes(), self.store.path.read_bytes()
        self.image.write_bytes(self.image.read_bytes() + b'new revision')
        self._interrupt_promotion('/installation.json')
        self.assertTrue(user_install.recover_install(self.store))
        self.assertEqual(image.read_bytes(), before_image)
        self.assertEqual(self.store.path.read_bytes(), before_settings)
        self.assertFalse(list(self.store.data_dir.glob('.application-staged-*')))
        self.assertEqual(json.loads((self.store.state_dir / 'installation.json').read_text())['image_sha256'], backend.digest(image))

    def test_power_failure_after_commit_finishes_backup_cleanup(self):
        self.install()
        self.image.write_bytes(self.image.read_bytes() + b'new candidate')
        self._interrupt_promotion('committed-journal')
        image = self.store.data_dir / 'application.AppImage'
        self.assertEqual(image.read_bytes(), self.image.read_bytes())
        self.assertTrue(list(self.store.data_dir.glob('.application-staged-*.previous')))
        self.assertFalse(user_install.recover_install(self.store))
        self.assertEqual(image.read_bytes(), self.image.read_bytes())
        self.assertFalse(list(self.store.data_dir.glob('.application-staged-*')))
        self.assertNotIn('cleanup', json.loads((self.store.state_dir / 'install-journal.json').read_text()))

    def test_outer_update_rollback_allows_exact_previous_image_during_native_recovery(self):
        self.install()
        image = self.store.data_dir / 'application.AppImage'
        old_image = image.read_bytes()
        old_receipt = (self.store.state_dir / 'installation.json').read_bytes()
        package = self.public.parent / backend.PACKAGE_NAME
        old_native = (package / 'native-v2.so').read_bytes()
        (self.bundle / 'native-v2.so').write_bytes(b'new inert native revision')
        manifest = json.loads((self.bundle / 'manifest.json').read_text())
        manifest['files']['native-v2.so'] = backend.digest(self.bundle / 'native-v2.so')
        atomic_json(self.bundle / 'manifest.json', manifest)
        # The outer updater already selected candidate image before native setup.
        image.write_bytes(old_image + b'candidate AppImage revision')
        self._interrupt_promotion('/native-v2.so', image=image)
        self.assertNotEqual((package / 'native-v2.so').read_bytes(), old_native)
        # Its failed health check restores exactly the prior executable inode.
        image.write_bytes(old_image)
        self.assertTrue(user_install.recover_install(self.store))
        self.assertEqual(image.read_bytes(), old_image)
        self.assertEqual((package / 'native-v2.so').read_bytes(), old_native)
        self.assertEqual((self.store.state_dir / 'installation.json').read_bytes(), old_receipt)
        self.assertEqual(backend._identity(backend.verified_original(self.public)), self.identity)

    def test_real_store_receipt_supports_bootstrap_reopening_download(self):
        from unity_scale.__main__ import bootstrap_appimage
        bootstrap_appimage(store=self.store, source=self.image,
            installer=lambda source, **_kwargs: self.install(source))
        receipt = json.loads((self.store.state_dir / 'installation.json').read_text())
        self.assertEqual(receipt['version'], core.VERSION)
        executions = []
        bootstrap_appimage(store=self.store, source=self.image,
            installer=lambda *_args, **_kwargs: self.fail('Repeated same-version download must dispatch installed app'),
            execute=lambda *args: executions.append(args))
        self.assertEqual(executions[0][0], str(self.store.data_dir / 'application.AppImage'))
        self.assertEqual(executions[0][1][1:], ['gui'])

    def test_early_staging_failure_keeps_existing_journal_and_files(self):
        self.install()
        image = self.store.data_dir / 'application.AppImage'
        journal = self.store.state_dir / 'install-journal.json'
        old_journal, old_image, old_settings = journal.read_bytes(), image.read_bytes(), self.store.path.read_bytes()
        with patch.object(user_install.shutil, 'copyfile', side_effect=OSError('disk full')), \
                patch.object(backend, '_atomic_bytes', side_effect=AssertionError('Do not rewrite untouched files')):
            with self.assertRaisesRegex(OSError, 'disk full'):
                self.install()
        self.assertEqual(journal.read_bytes(), old_journal)
        self.assertEqual(image.read_bytes(), old_image)
        self.assertEqual(self.store.path.read_bytes(), old_settings)
        self.assertFalse(list(self.store.data_dir.glob('.application-staged-*')))

    def test_interrupted_migration_refuses_foreign_launcher_before_recovery(self):
        self._interrupt_promotion('/Editor/Unity')
        self.public.write_bytes(b'foreign Editor upgrade')
        with self.assertRaisesRegex(core.AppError, 'launcher changed'):
            user_install.recover_install(self.store)
        self.assertEqual(self.public.read_bytes(), b'foreign Editor upgrade')
        self.assertTrue((self.public.parent / backend.BACKUP_NAME).exists())

    def test_complete_uninstall_restores_original_and_retains_settings(self):
        self.install()
        self.store.set_profile(self.public, dict(ui_scale_percent=150, follow_desktop=False, render_scale=2, override_enabled=True))
        with patch.object(user_install, '_app_closed'):
            result = user_install.uninstall_user(self.store, editors=[self.public])
        self.assertTrue(result['uninstalled'])
        self.assertEqual(backend._identity(self.public), self.identity)
        self.assertEqual(self.public.read_bytes(), self.original)
        self.assertFalse((self.public.parent / backend.PACKAGE_NAME).exists())
        self.assertFalse((self.store.data_dir / 'application.AppImage').exists())
        self.assertEqual(self.store.get_profile(self.public)['ui_scale_percent'], 150)

    def test_v1_migration_preserves_150_profiles_extras_and_original_inode(self):
        self.legacy_connection()
        self.install()
        self.assertEqual(self.store.get_profile(self.public)['ui_scale_percent'], 150)
        self.assertTrue(self.store.get_profile(self.public)['override_enabled'])
        self.assertEqual(self.store.get_profile(self.public)['control_revision'], 7)
        self.assertIn('/additional/2022.3.1f1/Editor/Unity', self.store.load()['extra_editors'])
        self.assertEqual(backend._identity(backend.verified_original(self.public)), self.identity)
        package = self.public.parent / backend.PACKAGE_NAME
        self.assertTrue((package / 'receipt.json').exists())
        self.assertTrue((package / 'native.so').exists())
        self.assertTrue(user_install._legacy_settings(self.store).exists())

    def test_final_integration_failure_restores_app_settings_and_v1_connection(self):
        self.legacy_connection()
        before_public = self.public.read_bytes()
        before_receipt = (self.public.parent / backend.PACKAGE_NAME / 'receipt.json').read_bytes()
        self.store.data_dir.mkdir(parents=True, exist_ok=True)
        image = self.store.data_dir / 'application.AppImage'
        image.write_bytes(b'old image')
        atomic_json(self.store.path, {'schema_version': 2, 'editors': {}, 'extra_editors': []})
        before_settings = self.store.path.read_bytes()
        actual = backend._atomic_bytes
        def fail(path, *args):
            if path.suffix == '.desktop':
                raise OSError('injected desktop failure')
            return actual(path, *args)
        with patch.object(backend, '_atomic_bytes', side_effect=fail):
            with self.assertRaisesRegex(OSError, 'desktop failure'):
                self.install()
        self.assertEqual(image.read_bytes(), b'old image')
        self.assertEqual(self.store.path.read_bytes(), before_settings)
        self.assertEqual(self.public.read_bytes(), before_public)
        self.assertEqual((self.public.parent / backend.PACKAGE_NAME / 'receipt.json').read_bytes(), before_receipt)
        self.assertFalse((self.public.parent / backend.PACKAGE_NAME / 'activation.json').exists())
        self.assertEqual(backend._identity(backend.verified_original(self.public)), self.identity)

    def test_running_preserved_original_refuses_before_any_migration(self):
        self.legacy_connection()
        backup = self.public.parent / backend.BACKUP_NAME
        actual = backend._running
        checked = []
        def running(path):
            checked.append(path)
            if path == backup:
                raise backend.LaunchError('Close this Editor')
        with patch.object(backend, '_running', side_effect=running):
            with self.assertRaisesRegex(ValueError, 'Close this Editor'):
                self.install()
        self.assertIn(backup, checked)
        self.assertFalse(self.store.path.exists())
        self.assertFalse((self.store.data_dir / 'application.AppImage').exists())

    def test_tampered_bundle_or_original_refuses_before_settings_move(self):
        self.legacy_connection()
        (self.bundle / 'native-v2.so').write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'runtime changed'):
            self.install()
        self.assertFalse(self.store.path.exists())
        self.assertFalse((self.store.data_dir / 'application.AppImage').exists())

    def test_v2_rollback_retains_a_foreign_public_update(self):
        plan = backend.ConnectionPlan(self.public, self.store.path, bundle=self.bundle)
        plan.apply()
        self.public.write_bytes(b'foreign editor update')
        with self.assertRaisesRegex(ValueError, 'foreign file retained'):
            plan.rollback()
        self.assertEqual(self.public.read_bytes(), b'foreign editor update')
        self.assertEqual(backend._identity(self.public.parent / backend.BACKUP_NAME), self.identity)

    def test_current_xdg_choices_win_and_same_managed_image_can_reinstall(self):
        self.legacy_connection()
        self.store.set_profile(self.public, dict(ui_scale_percent=175, follow_desktop=False, render_scale=2,
                                                 override_enabled=False))
        self.install()
        self.install(self.store.data_dir / 'application.AppImage')
        self.assertEqual(self.store.get_profile(self.public)['ui_scale_percent'], 175)
        self.assertFalse(self.store.get_profile(self.public)['override_enabled'])
        self.assertEqual(backend._identity(backend.verified_original(self.public)), self.identity)

    def test_cleanup_needs_exact_artifact_proof_and_removes_only_owned_files(self):
        self.install()
        owned = self.store.data_dir / 'unity_scale/owned.py'
        owned.parent.mkdir()
        owned.write_text('old app')
        unknown = owned.with_name('user-file')
        unknown.write_text('retain')
        atomic_json(self.store.data_dir / 'install-manifest.json', {'files': {'unity_scale/owned.py': backend.digest(owned)}})
        with self.assertRaises(core.AppError):
            user_install.cleanup_legacy(self.store, proof={'runtime_verified': True, 'image_sha256': 'wrong'})
        result = user_install.cleanup_legacy(self.store, proof={'runtime_verified': True,
            'image_sha256': backend.digest(self.store.data_dir / 'application.AppImage')})
        self.assertEqual(result['removed'], ['unity_scale/owned.py'])
        self.assertTrue(unknown.exists())

    def test_native_v1_cleanup_is_separate_from_promotion_and_preserves_unknown_leaves(self):
        self.legacy_connection()
        self.install()
        package = self.public.parent / backend.PACKAGE_NAME
        unknown = package / 'user-notes'
        unknown.write_text('retain')
        proof = dict(runtime_verified=True, image_sha256=backend.digest(self.store.data_dir / 'application.AppImage'))
        result = user_install.cleanup_legacy(self.store, proof=proof)
        self.assertEqual(result['native_removed'][str(self.public)], ['wrapper', 'native.so', 'receipt.json'])
        self.assertTrue(unknown.exists())
        self.assertTrue((package / 'activation.json').exists())
        self.assertEqual(backend._identity(backend.verified_original(self.public)), self.identity)


if __name__ == '__main__':
    unittest.main()
