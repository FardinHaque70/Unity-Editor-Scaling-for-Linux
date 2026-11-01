import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from unity_scale.core import AppError, Store, discover_editors, inspect_editor, launch_command, validate_profile


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {"XDG_CONFIG_HOME":str(self.root/'config'), "XDG_STATE_HOME":str(self.root/'state'), "XDG_DATA_HOME":str(self.root/'data')})
        self.env.start()

    def tearDown(self):
        self.env.stop();self.temp.cleanup()

    def editor(self, version="6000.3.27f2"):
        target = self.root/version/'Editor/Unity'
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(b'\x7fELF not executed by discovery');target.chmod(0o755)
        (target.parent/'Data/Managed').mkdir(parents=True,exist_ok=True)
        (target.parent/'Data/Managed/UnityEditor.dll').write_bytes(b'MZ test fixture')
        (target.parent/'Data/Resources').mkdir(parents=True,exist_ok=True)
        return target

    def test_editor_settings_apply_independently_of_project(self):
        first, second = self.editor(), self.editor("6000.4.0f1")
        store=Store();store.set_profile(first,{"ui_scale_percent":160})
        self.assertEqual(store.get_profile(first)["ui_scale_percent"],160)
        self.assertEqual(store.get_profile(second)["ui_scale_percent"],150)
        self.assertFalse(any(self.root.glob('**/ScalingAudit')))
        self.assertEqual(store.path.stat().st_mode & 0o777,0o600)

    def test_discovery_never_executes_and_detects_version(self):
        target=self.editor();editor=inspect_editor(target.parent.parent)
        self.assertEqual(editor.version,"6000.3.27f2")
        with patch('unity_scale.core.subprocess.check_output',side_effect=AssertionError('must not execute')):
            self.assertTrue(any(e.path==str(target) for e in discover_editors([str(target)])))
        bad=self.root/'Unity';bad.write_text('#!/bin/sh\necho fake');bad.chmod(0o755)
        with self.assertRaises(AppError):inspect_editor(bad)

    def test_manual_editor_rejects_native_executable_without_editor_data(self):
        invalid=self.root/'not-an-editor/Unity';invalid.parent.mkdir()
        invalid.write_bytes(b'\x7fELF');invalid.chmod(0o755)
        with self.assertRaisesRegex(AppError, 'valid Unity Editor installation'):
            Store().add_editor(invalid)
        self.assertFalse(Store().path.exists())

    def test_atomic_settings_corruption_is_not_silently_overwritten(self):
        store=Store();store.config_dir.mkdir(parents=True);store.path.write_text('{broken')
        with self.assertRaises(AppError):store.set_profile(self.editor(),{"ui_scale_percent":150})
        self.assertEqual(store.path.read_text(),'{broken')

    def test_rejects_unusable_scale_and_config_values(self):
        for value in [float('nan'),float('inf'),True,0,99,201,150.5,'150']:
            with self.subTest(value=value),self.assertRaises(AppError):validate_profile({'ui_scale_percent':value})
        with self.assertRaises(AppError):validate_profile({'follow_desktop':'false'})
        with self.assertRaises(AppError):validate_profile({'cursor_size':0})

    def test_malformed_saved_editor_entries_are_actionable_errors(self):
        store=Store();store.config_dir.mkdir(parents=True)
        for bad in [{'schema_version':1,'editors':{},'extra_editors':[5]}, {'schema_version':1,'editors':{'/example/Unity':[]},'extra_editors':[]}]:
            store.path.write_text(json.dumps(bad))
            with self.assertRaises(AppError):store.load()
        with self.assertRaises(AppError):validate_profile({'render_scale':2.0})

    def test_running_scale_ignores_stale_and_different_editor_metadata(self):
        from unity_scale.core import get_running_scale
        path=Store().state_dir/'runs/20261101T000000Z/launch.json';path.parent.mkdir(parents=True)
        target=self.editor()
        # Reused/current pid cannot count as a scaled Editor without the
        # independently matched private display and child marker.
        path.write_text(json.dumps({'editor':str(target),'status':'running','editor_pid':os.getpid(),'display':':119'}))
        self.assertIsNone(get_running_scale(target))
        path.write_text('{bad')
        self.assertIsNone(get_running_scale(target))

    def test_launch_command_preserves_paths_and_arguments_as_vector(self):
        target=self.editor();project=self.root/'Game with spaces; $(not-a-shell)'
        cmd=launch_command(str(target),str(project),['-custom','a; b'])
        self.assertIn(str(project),cmd);self.assertEqual(cmd[-3:],['--','-custom','a; b'])
        self.assertNotIn('-projectPath',launch_command(str(target)))

    def test_located_editors_persist_and_remove_without_deleting_installation(self):
        target=self.editor();store=Store();store.add_editor(str(target));store.add_editor(str(target))
        self.assertEqual(store.load()['extra_editors'],[str(target)])
        store.remove_editor(str(target));self.assertEqual(store.load()['extra_editors'],[]);self.assertTrue(target.exists())


if __name__=='__main__':unittest.main()
