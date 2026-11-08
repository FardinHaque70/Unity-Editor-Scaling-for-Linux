"""Regression checks for the generated, private production-update controller.

These exercise its handoff/result contract, not the updater's signature or GUI
health logic, which are covered by separate artifact checks.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "qa/check_production_update.py"
SPEC = importlib.util.spec_from_file_location("production_update_qa", SCRIPT)
QA = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(QA)


class ProductionUpdateControllerTests(unittest.TestCase):
    def test_generated_controller_compiles(self):
        compile(QA.CASE_CONTROLLER, "case-controller.py", "exec")

    def test_committed_or_restored_image_records_pass(self):
        for mode in ("success", "rollback"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                target = root / "application.AppImage"
                target.write_bytes(b"controlled update result")
                digest = hashlib.sha256(target.read_bytes()).hexdigest()
                state = root / "state"
                state.mkdir()
                (state / "installation.json").write_text(json.dumps({"image_sha256": digest}))
                result = root / "result.json"
                result.write_text(json.dumps({
                    "mode": mode, "target": str(target), "stage": str(root / "absent-stage"),
                    "state_dir": str(state), "expected_sha256": digest if mode == "success" else "wrong",
                    "previous_sha256": digest if mode == "rollback" else "wrong",
                }))
                controller = root / "case-controller.py"
                controller.write_text(QA.CASE_CONTROLLER)
                process = subprocess.run([sys.executable, str(controller), sys.executable, "-c", "pass"],
                    env=dict(os.environ, QA_UPDATE_RESULT=str(result)), capture_output=True, text=True, timeout=10)
                self.assertEqual(process.returncode, 0, process.stderr)
                record = json.loads(result.read_text())
                self.assertEqual(record["status"], "PASS")
                self.assertEqual(record["final_sha256"], digest)
                self.assertTrue(record["rollback_removed"])
                self.assertTrue(record["staging_removed"])

    def test_worker_failure_is_propagated_before_result_handling(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            controller = root / "case-controller.py"
            controller.write_text(QA.CASE_CONTROLLER)
            result = root / "must-not-be-created.json"
            process = subprocess.run([sys.executable, str(controller), sys.executable, "-c", "raise SystemExit(23)"],
                env=dict(os.environ, QA_UPDATE_RESULT=str(result)), capture_output=True, text=True, timeout=10)
            self.assertEqual(process.returncode, 23, process.stderr)
            self.assertFalse(result.exists())


if __name__ == "__main__":
    unittest.main()
