# -*- coding: utf-8 -*-
"""Native single-window shell: only opens one WebView2 window."""

import sys
import unittest
from unittest.mock import MagicMock, patch

import desktop_window


class DesktopWindowTests(unittest.TestCase):
    def test_run_opens_one_window_and_blocks_until_close(self):
        fake = MagicMock()
        with patch.dict(sys.modules, {"webview": fake}):
            self.assertTrue(desktop_window.run("http://127.0.0.1:8765"))

        fake.create_window.assert_called_once()
        args, kwargs = fake.create_window.call_args
        self.assertEqual(desktop_window.TITLE, args[0])
        self.assertEqual("http://127.0.0.1:8765", args[1])
        self.assertNotIn("maximized", kwargs)
        fake.start.assert_called_once_with(debug=False, private_mode=False)

    def test_missing_webview_falls_back(self):
        with patch.dict(sys.modules, {"webview": None}):
            self.assertFalse(desktop_window.run("http://127.0.0.1:8765"))


if __name__ == "__main__":
    unittest.main()
