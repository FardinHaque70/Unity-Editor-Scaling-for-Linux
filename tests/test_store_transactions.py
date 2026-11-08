from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from unity_scale.private_store import Store, atomic_json


class StoreTransactionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='unity-settings-')
        self.addCleanup(temporary.cleanup)
        self.store = Store(Path(temporary.name))
        self.editor = '/example/6000.3.27f2/Editor/Unity'

    def test_actual_before_state_includes_another_writers_latest_change(self):
        stale = self.store.get_profile(self.editor)
        other = Store(self.store.root)
        other.set_profile(self.editor, dict(stale, override_enabled=True, ui_scale_percent=160))
        document = other.load()
        document['editors'][self.editor]['future_setting'] = 'preserve'
        atomic_json(other.path, document)
        before, after = self.store.set_profile_change(self.editor, dict(stale, override_enabled=True, ui_scale_percent=175))
        self.assertEqual(before['ui_scale_percent'], 160)
        self.assertEqual(after['ui_scale_percent'], 175)
        self.assertEqual(after['future_setting'], 'preserve')
        self.assertEqual(self.store.get_profile(self.editor), after)

    def test_failed_atomic_save_keeps_preferences_and_removes_temp_file(self):
        initial = self.store.set_profile(self.editor, self.store.get_profile(self.editor))
        original_bytes = self.store.path.read_bytes()
        with patch('unity_scale.private_store.os.replace', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.store.set_profile_change(self.editor, dict(initial, override_enabled=True))
        self.assertEqual(self.store.path.read_bytes(), original_bytes)
        self.assertEqual(sorted(p.name for p in self.store.config_dir.iterdir()), ['.settings.lock', 'settings.json'])

    def test_default_retains_custom_value_and_profiles_are_independent(self):
        initial = self.store.get_profile(self.editor)
        self.store.set_profile(self.editor, dict(initial, override_enabled=True, ui_scale_percent=145))
        second = '/example/2022.3.1f1/Editor/Unity'
        self.store.set_profile(second, dict(initial, override_enabled=True, ui_scale_percent=175))
        before, after = self.store.set_profile_change(self.editor, dict(initial, override_enabled=False, ui_scale_percent=145))
        self.assertTrue(before['override_enabled'])
        self.assertFalse(after['override_enabled'])
        self.assertEqual(after['ui_scale_percent'], 145)
        self.assertEqual(self.store.get_profile(second)['ui_scale_percent'], 175)


if __name__ == '__main__':
    unittest.main()
