import unittest
from unity_scale.gui_state import EditorEditState, parse_scale


class EditorEditStateTests(unittest.TestCase):
    def test_whole_value_validation_never_clamps_malformed_input(self):
        for text in ["", "1", "20", "201", "999", "150.0", "150%", " 150", "0150", "x"]:
            self.assertIsNone(parse_scale(text), text)
        self.assertEqual(parse_scale("100"), 100)
        self.assertEqual(parse_scale("200"), 200)

    def test_latest_value_survives_an_older_inflight_completion(self):
        state = EditorEditState(150, True)
        state.edit_text("160")
        first = state.begin()
        state.edit_text("170")
        state.edit_text("180")
        self.assertIsNone(state.begin())
        state.complete(first)
        self.assertTrue(state.pending)
        self.assertEqual(state.saved_scale, 160)
        last = state.begin()
        self.assertEqual(last.scale, 180)
        state.complete(last)
        self.assertFalse(state.pending)
        self.assertEqual(state.saved_scale, 180)

    def test_failed_save_is_dirty_until_explicit_retry_or_discard(self):
        state = EditorEditState(150, True)
        state.edit_text("160")
        request = state.begin()
        state.complete(request, error="disk full")
        self.assertTrue(state.pending)
        self.assertIn("Not saved", state.subtitle())
        self.assertEqual(state.saved_scale, 150)
        retry = state.begin()
        state.complete(retry)
        self.assertFalse(state.pending)

    def test_invalid_text_requires_confirmation_and_cannot_be_saved(self):
        state = EditorEditState(150, True)
        state.edit_text("999")
        self.assertTrue(state.pending)
        self.assertIsNone(state.begin())
        self.assertEqual(state.saved_scale, 150)
        state.discard()
        self.assertFalse(state.pending)

    def test_running_and_next_labels_follow_committed_settings(self):
        state = EditorEditState(150, True)
        state.edit_text("160")
        request = state.begin()
        self.assertIn("150%", state.subtitle(150))
        state.complete(request)
        self.assertEqual(state.subtitle(150), "Running 150% · Next 160%")
        state.set_override(False)
        state.complete(state.begin())
        self.assertEqual(state.subtitle(150), "Running 150% · Override off next launch")
        self.assertNotIn("Next 160%", state.subtitle(150))
        self.assertEqual(state.subtitle(), "Override off")

    def test_discard_waits_for_the_active_save(self):
        state = EditorEditState(150, True)
        state.edit_text("160")
        request = state.begin()
        state.edit_text("170")
        with self.assertRaises(ValueError):
            state.discard()
        state.complete(request)
        state.discard()
        self.assertEqual(state.text, "160")
        self.assertFalse(state.pending)


if __name__ == "__main__":
    unittest.main()
