# -*- coding: utf-8 -*-
"""Box battle tag is persisted and applied without the manual user-ID field."""

import unittest
from unittest.mock import patch

import web_ui


class BoxNameSyncTests(unittest.TestCase):
    def test_new_box_tag_is_saved_and_applied(self):
        cfg = {"name": "", "log_root": "D:\\Hearthstone\\Logs"}
        with (
            patch.object(web_ui, "_read_box_player_tag",
                         return_value="Player#12345"),
            patch.object(web_ui, "load_config", return_value=dict(cfg)),
            patch.object(web_ui, "save_config") as save_config,
            patch.object(web_ui, "_apply_constants") as apply_constants,
            patch.object(web_ui, "_log"),
        ):
            self.assertTrue(web_ui._sync_name_from_box())

        saved = save_config.call_args[0][0]
        self.assertEqual("Player#12345", saved["name"])
        self.assertEqual("D:\\Hearthstone\\Logs", saved["log_root"])
        apply_constants.assert_called_once_with(
            "Player#12345", "D:\\Hearthstone\\Logs")

    def test_same_tag_does_not_rewrite_config(self):
        cfg = {"name": "Player#12345", "log_root": "D:\\Logs"}
        with (
            patch.object(web_ui, "_read_box_player_tag",
                         return_value="Player#12345"),
            patch.object(web_ui, "load_config", return_value=dict(cfg)),
            patch.object(web_ui, "save_config") as save_config,
            patch.object(web_ui, "_apply_constants") as apply_constants,
            patch.object(web_ui, "_log"),
        ):
            self.assertFalse(web_ui._sync_name_from_box())

        save_config.assert_not_called()
        apply_constants.assert_not_called()

    def test_missing_box_tag_keeps_cached_name(self):
        with (
            patch.object(web_ui, "_read_box_player_tag", return_value=""),
            patch.object(web_ui, "save_config") as save_config,
            patch.object(web_ui, "_apply_constants") as apply_constants,
        ):
            self.assertFalse(web_ui._sync_name_from_box())

        save_config.assert_not_called()
        apply_constants.assert_not_called()


if __name__ == "__main__":
    unittest.main()
