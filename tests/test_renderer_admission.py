"""Unity owns renderer arguments; scaling retains native-session safeguards."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest


class RendererAdmissionTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('cc'), 'Native compiler unavailable')
    def test_actual_native_argv_and_session_admission(self):
        script = Path(__file__).resolve().parents[1] / 'native/product/environment_check.py'
        result = subprocess.run([sys.executable, str(script)], check=True, capture_output=True, text=True, timeout=30)
        evidence = json.loads(result.stdout)
        self.assertEqual(evidence['session_renderer_cases'], 40)
        self.assertTrue(any(c['argv'] == ['-force-vulkan'] and c['result'] == 0 for c in evidence['cases']))
        self.assertTrue(any(c['argv'] == ['-force-vulkan', '-FORCE-D3D12'] and c['result'] == 0 for c in evidence['cases']))
        self.assertFalse(evidence['Unity_run'])
