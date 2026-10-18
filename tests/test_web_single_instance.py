# -*- coding: utf-8 -*-
"""Only one console instance may run at a time."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import web_ui


class SingleInstanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.port_file = Path(self.tmp.name) / "ui_port.txt"
        self.port_file.write_text(
            json.dumps({"url": "http://127.0.0.1:8765"}), encoding="utf-8")
        self._port_patch = patch.object(web_ui, "PORT_FILE", self.port_file)
        self._port_patch.start()

    def tearDown(self):
        self._port_patch.stop()
        self.tmp.cleanup()

    def test_existing_instance_is_focused_and_new_process_stops(self):
        response = MagicMock()
        response.__enter__ = MagicMock(return_value=response)
        response.__exit__ = MagicMock(return_value=False)
        with (
            patch.object(web_ui.urllib.request, "urlopen", return_value=response),
            patch.object(web_ui.desktop_window, "focus_existing_window",
                         return_value=True) as focus,
            patch.object(web_ui.sys, "argv", ["web_ui.py"]),
        ):
            self.assertTrue(web_ui._activate_existing_instance())
        focus.assert_called_once()

    def test_new_instance_flag_bypasses_the_check(self):
        with patch.object(web_ui.sys, "argv", ["web_ui.py", "--new-instance"]):
            self.assertFalse(web_ui._activate_existing_instance())

    def test_unreachable_port_file_does_not_block_start(self):
        with (
            patch.object(web_ui.urllib.request, "urlopen",
                         side_effect=OSError("connection refused")),
            patch.object(web_ui.sys, "argv", ["web_ui.py"]),
        ):
            self.assertFalse(web_ui._activate_existing_instance())


if __name__ == "__main__":
    unittest.main()
