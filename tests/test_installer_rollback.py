"""Application/native coordinator recovery; all paths are temporary fixtures."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('app_installer', Path(__file__).resolve().parents[1] / 'install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallerRollbackTests(unittest.TestCase):
    def test_native_restore_failure_does_not_skip_other_editors_or_application_files(self):
        with tempfile.TemporaryDirectory(prefix='unity-app-rollback-') as temporary:
            root = Path(temporary)
            current, previous = root / 'app', root / 'previous'
            current.mkdir()
            (current / 'version').write_text('new')
            previous.mkdir()
            (previous / 'version').write_text('old')
            launcher, desktop, absent = root / 'launcher', root / 'desktop', root / 'absent-before'
            for path in (launcher, desktop, absent):
                path.write_bytes(b'new')
            old_files = {launcher: (b'old launcher', 0o755), desktop: (b'old desktop', 0o644), absent: None}
            restored = []
            def restore(public):
                restored.append(public)
                if public == 'second':
                    raise ValueError('foreign editor update; do not overwrite')
            with patch.object(installer, 'DESTINATION', current):
                errors = installer.rollback_update(['first', 'second'], True, True, previous, old_files, restore)
            self.assertEqual(restored, ['second', 'first'])
            self.assertEqual(len(errors), 1)
            self.assertIn('foreign editor update', errors[0])
            self.assertEqual((current / 'version').read_text(), 'old')
            self.assertEqual(launcher.read_bytes(), b'old launcher')
            self.assertEqual(desktop.read_bytes(), b'old desktop')
            self.assertFalse(absent.exists())


if __name__ == '__main__':
    unittest.main()
