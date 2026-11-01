"""Pure GUI boundary checks; the rendering smoke is explicitly opt-in."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

try:
    from unity_scale import core
    from unity_scale.gui import diagnostic_text, edited_profile, editor_paths, integration_action, start_editor, known_editors, apply_editor_override, editor_title
except (ImportError, ValueError) as exc:
    raise unittest.SkipTest(f"GTK4/libadwaita GUI dependencies unavailable: {exc}")


class GuiBoundaryTests(unittest.TestCase):
    def test_saved_editor_paths_accept_profiles_and_explicit_locations(self):
        self.assertEqual(editor_paths({
            "editors": {"/hub/Editor/Unity": {"ui_scale_percent": 160}},
            "extra_editors": ["/hub/Editor/Unity", "/custom/Editor/Unity"],
        }), ["/hub/Editor/Unity", "/custom/Editor/Unity"])
        self.assertEqual(editor_paths({"editors": [{"path": "/old/Unity"}, None, 1]}), ["/old/Unity"])

    def test_visible_controls_preserve_advanced_profile_options(self):
        previous = {"ui_scale_percent": 150, "follow_desktop": False,
                    "render_scale": 3, "cursor_theme": "Breeze_Light",
                    "desktop_scale_percent": 145}
        changed = edited_profile(previous, 160, True)
        self.assertEqual(changed["ui_scale_percent"], 160)
        self.assertTrue(changed["follow_desktop"])
        self.assertEqual(changed["render_scale"], 3)
        self.assertEqual(changed["cursor_theme"], "Breeze_Light")
        self.assertEqual(previous["ui_scale_percent"], 150)
        self.assertFalse(previous["follow_desktop"])

    def test_interrupted_integration_offers_restore_instead_of_enable(self):
        self.assertEqual(integration_action({"enabled": False, "can_disable": True}), "disable")
        self.assertEqual(integration_action({"enabled": True}), "disable")
        self.assertEqual(integration_action({"enabled": False, "can_enable": True}), "enable")

    def test_diagnostics_include_only_explicit_support_information(self):
        editor = core.Editor("/Editor/Unity", "6000.3.27f2", "Unity 6.3 LTS", "Test")
        with patch("unity_scale.gui.core.diagnostics", return_value={
                "application": "Unity Scale", "project_paths_included": False,
                "raw_logs_included": False}):
            text = diagnostic_text(editor, {"ui_scale_percent": 150,
                                           "cursor_theme": "/private/cursor/theme"})
        snapshot = json.loads(text)
        self.assertEqual(snapshot["editor_version"], "6000.3.27f2")
        self.assertEqual(snapshot["profile"]["ui_scale_percent"], 150)
        self.assertFalse(snapshot["project_paths_included"])
        self.assertFalse(snapshot["raw_logs_included"])
        self.assertNotIn("/Editor/Unity", text)
        self.assertNotIn("/private/cursor/theme", text)
        self.assertNotIn("helper", snapshot)

    def test_startup_reads_known_editors_without_scanning(self):
        editor = core.Editor("/saved/Unity", "6000.3.27f2", "Unity 6.3 LTS", "Test")
        store = SimpleNamespace(load=lambda: {"editors": {"/saved/Unity": {}}, "extra_editors": []})
        with patch("unity_scale.gui.core.inspect_editor", return_value=editor), \
             patch("unity_scale.gui.core.discover_editors") as scan:
            self.assertEqual(known_editors(store), [editor])
            scan.assert_not_called()
        self.assertEqual(editor_title(editor), "Unity 6.3 LTS (6000.3.27f2)")

    def test_apply_off_restores_without_saving_or_requiring_supported_desktop(self):
        store = SimpleNamespace(set_profile=Mock())
        with patch("unity_scale.integration.disable", return_value={"enabled": False}) as disable, \
             patch("unity_scale.gui.core.environment_status") as environment:
            self.assertEqual(apply_editor_override(store, "/Editor/Unity", {}, False), {"enabled": False})
            disable.assert_called_once_with("/Editor/Unity")
            store.set_profile.assert_not_called()
            environment.assert_not_called()

    def test_apply_on_checks_then_saves_then_enables(self):
        calls = []
        store = SimpleNamespace(set_profile=lambda *_: calls.append("save"))
        with patch("unity_scale.gui.core.environment_status", side_effect=lambda: (calls.append("check") or {"supported": True})), \
             patch("unity_scale.integration.enable", side_effect=lambda _path: (calls.append("enable") or {"enabled": True})):
            apply_editor_override(store, "/Editor/Unity", {"ui_scale_percent": 150}, True)
        self.assertEqual(calls, ["check", "save", "enable"])

    def test_apply_on_unsupported_desktop_performs_no_mutation(self):
        store = SimpleNamespace(set_profile=Mock())
        with patch("unity_scale.gui.core.environment_status", return_value={"supported": False, "summary": "Unsupported desktop"}), \
             patch("unity_scale.integration.enable") as enable:
            with self.assertRaisesRegex(core.AppError, "Unsupported desktop"):
                apply_editor_override(store, "/Editor/Unity", {}, True)
            store.set_profile.assert_not_called()
            enable.assert_not_called()

    def test_launch_preflight_failure_never_spawns_unity(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SimpleNamespace(state_dir=Path(folder), set_profile=Mock())
            with patch("unity_scale.runner.launch_plan", return_value={
                    "mode": "scaled", "environment_status": {"supported": False, "summary": "Missing bridge"}}), \
                 patch("unity_scale.gui.subprocess.Popen") as spawn:
                with self.assertRaisesRegex(core.AppError, "Missing bridge"):
                    start_editor(store, "/Editor/Unity", {"ui_scale_percent": 150})
                spawn.assert_not_called()

    def test_launch_immediate_failure_exposes_runner_error(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SimpleNamespace(state_dir=Path(folder), set_profile=Mock())
            def fail(_command, **kwargs):
                kwargs["stdout"].write("A project lock is already held.\n")
                kwargs["stdout"].flush()
                return SimpleNamespace(wait=lambda **_kwargs: 2)
            with patch("unity_scale.runner.launch_plan", return_value={
                    "mode": "scaled", "environment_status": {"supported": True}}), \
                 patch("unity_scale.gui.subprocess.Popen", side_effect=fail):
                with self.assertRaisesRegex(core.AppError, "project lock is already held"):
                    start_editor(store, "/Editor/Unity", {"ui_scale_percent": 150})
            self.assertEqual((Path(folder) / "gui-launch.log").stat().st_mode & 0o777, 0o600)

    def test_launch_detaches_and_leaves_a_running_editor_alone(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SimpleNamespace(state_dir=Path(folder), set_profile=Mock())
            process = Mock()
            process.wait.side_effect = subprocess.TimeoutExpired("unity-scale", 1)
            with patch("unity_scale.runner.launch_plan", return_value={
                    "mode": "scaled", "environment_status": {"supported": True}}), \
                 patch("unity_scale.gui.core.launch_command", return_value=["entry", "run"]), \
                 patch("unity_scale.gui.subprocess.Popen", return_value=process) as spawn:
                path = start_editor(store, "/Editor/Unity", {"ui_scale_percent": 150})
            self.assertEqual(path.name, "gui-launch.log")
            self.assertTrue(spawn.call_args.kwargs["start_new_session"])
            process.terminate.assert_not_called()
            process.kill.assert_not_called()

    @unittest.skipUnless(os.environ.get("UNITY_SCALE_TEST_GUI") == "1",
                         "Set UNITY_SCALE_TEST_GUI=1 on a graphical desktop for GTK smoke")
    def test_gui_smoke_never_displays_or_changes_an_editor(self):
        env = dict(os.environ, GSETTINGS_BACKEND="memory")
        result = subprocess.run([sys.executable, "-m", "unity_scale.gui", "--smoke-test"],
                                env=env, text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("no windows shown, no settings or Editor changed", result.stdout)


if __name__ == "__main__":
    unittest.main()
