"""Non-presenting GTK autosave integration tests using an in-memory backend."""
import os
import threading
import time
import unittest
from unittest.mock import Mock, patch

if os.environ.get("UNITY_SCALE_TEST_GUI") != "1":
    raise unittest.SkipTest("Set UNITY_SCALE_TEST_GUI=1 on a graphical desktop for GTK async tests")

from unity_scale import core
from unity_scale.gui import UnityScaleApplication, UnityScaleWindow
from gi.repository import GLib, Gtk


def pump_until(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    context = GLib.MainContext.default()
    while time.monotonic() < deadline:
        while context.pending():
            context.iteration(False)
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("GTK async operation did not finish")


class GtkAutosaveTests(unittest.TestCase):
    sequence = 0

    def setUp(self):
        if not Gtk.init_check():
            self.skipTest("No graphical GTK display")
        self.app = UnityScaleApplication(smoke_test=True)
        type(self).sequence += 1
        self.app.set_application_id(f"{core.APP_ID}.Test{self.sequence}")
        self.app.register(None)
        self.window = UnityScaleWindow(self.app, smoke_test=True)
        self.app.window = self.window
        self.row = self.window.rows[0]
        self.row.set_state({"ui_scale_percent": 150, "render_scale": 2, "follow_desktop": False},
                           {"enabled": True, "state": "enabled"}, 150)
        self.window.smoke_test = False
        self.window.error = Mock()
        self.status = patch("unity_scale.integration.status", return_value={"enabled": True, "state": "enabled"})
        self.running = patch("unity_scale.core.get_running_scale", return_value=150)
        self.status.start()
        self.running.start()

    def tearDown(self):
        self.row.cancel_timer()
        self.window.closed = True
        self.window.destroy()
        self.app.quit()
        self.status.stop()
        self.running.stop()

    def test_debounce_saves_only_the_last_valid_value(self):
        original = self.window.store.set_profile
        save = Mock(side_effect=original)
        self.window.store.set_profile = save
        self.row.spin.set_text("160")
        self.row.spin.set_text("170")
        self.assertEqual(save.call_count, 0)
        pump_until(lambda: not self.row.state.pending)
        self.assertEqual(save.call_count, 1)
        self.assertEqual(save.call_args.args[1]["ui_scale_percent"], 170)
        self.assertEqual(self.row.get_subtitle(), "Running 150% · Next 170%")
        self.assertFalse(self.window.get_visible())

    def test_latest_edit_wins_after_an_inflight_save(self):
        entered, release = threading.Event(), threading.Event()
        values = []
        def slow(_path, profile):
            values.append(profile["ui_scale_percent"])
            if len(values) == 1:
                entered.set()
                if not release.wait(2):
                    raise RuntimeError("Test did not release the worker")
        self.window.store.set_profile = slow
        self.row.spin.set_text("160")
        self.row.flush()
        self.assertTrue(entered.wait(1))
        self.row.spin.set_text("170")
        self.row.spin.set_text("180")
        self.row.flush()
        release.set()
        pump_until(lambda: not self.row.state.pending)
        self.assertEqual(values, [160, 180])

    def test_failed_save_stays_dirty_and_close_requests_confirmation(self):
        self.window.store.set_profile = Mock(side_effect=core.AppError("Read-only settings"))
        self.row.spin.set_text("160")
        self.row.flush()
        pump_until(lambda: self.row.state.error is not None)
        self.assertTrue(self.row.state.dirty)
        self.assertIn("Not saved", self.row.get_subtitle())
        self.window.confirm_pending = Mock()
        self.assertTrue(self.window._on_close())
        self.window.confirm_pending.assert_called_once_with(self.window.rows, close=True)
        self.assertFalse(self.window.closed)

    def test_save_and_close_waits_for_inflight_callback(self):
        entered, release = threading.Event(), threading.Event()
        def slow(*_):
            entered.set()
            release.wait(2)
        self.window.store.set_profile = slow
        self.window.close = Mock()
        self.row.spin.set_text("160")
        self.row.flush()
        self.assertTrue(entered.wait(1))
        self.window.closing_mode = "save"
        self.window.maybe_finish_close()
        self.window.close.assert_not_called()
        release.set()
        pump_until(lambda: self.window.close.called)
        self.assertFalse(self.row.state.pending)

    def test_quit_action_routes_through_window_close(self):
        self.window.close = Mock()
        self.app.lookup_action("quit").activate(None)
        self.window.close.assert_called_once_with()

    def test_invalid_native_spin_text_survives_focus_update(self):
        self.row.spin.set_text("999")
        self.row.spin.update()
        self.assertEqual(self.row.spin.get_text(), "999")
        self.assertIsNone(self.row.state.value)
        self.assertTrue(self.row.state.pending)
        self.assertIsNone(self.row.state.inflight)


if __name__ == "__main__":
    unittest.main()
