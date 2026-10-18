# -*- coding: utf-8 -*-
"""Version is a single source of truth and is visible in UI/overlay/title."""

import unittest
from pathlib import Path

import desktop_window
import log_overlay
import web_ui
from version import __version__

ROOT = Path(__file__).resolve().parent.parent


class VersionTests(unittest.TestCase):
    def test_version_is_semver(self):
        self.assertRegex(__version__, r"^\d+\.\d+\.\d+$")

    def test_launcher_build_reads_version_py(self):
        script = (ROOT / "build" / "build-exe.ps1").read_text(encoding="utf-8")
        self.assertIn("version.py", script)
        self.assertIn("BuildInfo", script)
        launcher = (ROOT / "build" / "launcher" / "Launcher.cs").read_text(
            encoding="utf-8")
        self.assertIn("BuildInfo.Version", launcher)

    def test_window_and_overlay_show_version(self):
        self.assertIn(__version__, desktop_window.TITLE)
        self.assertIn(__version__, log_overlay.BRAND_NAME)
        self.assertEqual(__version__, web_ui.APP_VERSION)

    def test_page_has_version_slot_and_updates_title(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="appVersion"', html)
        self.assertIn('document.title = "HSLegendArriver v"', html)


if __name__ == "__main__":
    unittest.main()
