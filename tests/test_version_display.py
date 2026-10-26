# -*- coding: utf-8 -*-
"""Version is a single source of truth and is visible in UI/overlay/title."""

import unittest
from pathlib import Path

import desktop_window
import log_overlay
import web_ui
import version
from version import __version__

ROOT = Path(__file__).resolve().parent.parent


class VersionTests(unittest.TestCase):
    def test_version_is_semver(self):
        # 本分支沿用语义化版本（v1.3.25）；上游日期口径只是参考。
        self.assertRegex(__version__, r"^\d+\.\d+\.\d+$")
        self.assertEqual(__version__, version.VERSION)

    def test_launcher_build_reads_version_py(self):
        script = (ROOT / "build" / "build-exe.ps1").read_text(encoding="utf-8")
        self.assertIn("version.py", script)
        self.assertIn("BuildInfo", script)
        launcher = (ROOT / "build" / "launcher" / "Launcher.cs").read_text(
            encoding="utf-8")
        self.assertIn("BuildInfo.Version", launcher)

    def test_window_and_overlay_show_version(self):
        self.assertIn(version.version_label(), desktop_window.TITLE)
        self.assertEqual(log_overlay.VERSION_TEXT, version.version_label())
        self.assertEqual(log_overlay.BRAND_NAME, version.NAME)
        self.assertEqual(__version__, web_ui.APP_VERSION)

    def test_page_has_version_slot_and_updates_title(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="appVersion"', html)
        # 版本串来自 /api/status 的 version.label（v2026.10.27），不是前端自己拼。
        self.assertIn('verBox.textContent = vi.label;', html)
        self.assertIn('document.title = "HSLegendArriver " + vi.label', html)


if __name__ == "__main__":
    unittest.main()
