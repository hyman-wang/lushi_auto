# -*- coding: utf-8 -*-
"""盒子启动器：只测纯逻辑（不真的启动盒子）。"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import box_launcher


class PortTests(unittest.TestCase):
    def test_closed_port_is_false(self):
        self.assertFalse(box_launcher.port_open(port=1, timeout=0.05))


class EnsureBoxTests(unittest.TestCase):
    def test_already_ok_when_the_port_is_open(self):
        with patch.object(box_launcher, "port_open", return_value=True):
            result = box_launcher.ensure_box()

        self.assertTrue(result["ok"])
        self.assertEqual("already", result["action"])

    def test_running_without_port_needs_restart(self):
        with (
            patch.object(box_launcher, "port_open", return_value=False),
            patch.object(box_launcher, "_processes", return_value=[123]),
        ):
            result = box_launcher.ensure_box(restart=False)

        self.assertFalse(result["ok"])
        self.assertEqual("needs_restart", result["action"])

    def test_missing_exe(self):
        with (
            patch.object(box_launcher, "port_open", return_value=False),
            patch.object(box_launcher, "_processes", return_value=[]),
            patch.object(box_launcher, "box_path", return_value=None),
        ):
            result = box_launcher.ensure_box()

        self.assertFalse(result["ok"])
        self.assertEqual("missing", result["action"])

    def test_starts_the_box_with_the_debug_port(self):
        calls = []

        class FakeProc:
            pid = 4321
            returncode = None

            @staticmethod
            def poll():
                return None

        def fake_popen(argv, cwd=None):
            calls.append((argv, cwd))
            return FakeProc()

        opened = {"count": 0}

        def fake_port_open(port=9222, timeout=0.4):
            opened["count"] += 1
            return opened["count"] > 2   # 启动后第 3 次探测起算“端口已开”

        with (
            patch.object(box_launcher, "port_open", side_effect=fake_port_open),
            patch.object(box_launcher, "_processes", return_value=[]),
            patch.object(box_launcher, "box_path",
                         return_value=SimpleNamespace(
                             __str__=lambda self: r"D:\box\HSAng.exe",
                             parent=r"D:\box")),
            patch.object(box_launcher.subprocess, "Popen", side_effect=fake_popen),
            patch.object(box_launcher.time, "sleep", return_value=None),
        ):
            result = box_launcher.ensure_box(wait=5)

        self.assertTrue(result["ok"])
        self.assertEqual("started", result["action"])
        self.assertEqual(
            [r"--remote-debugging-port=9222"], calls[0][0][1:])

    def test_refuses_to_restart_while_hearthstone_is_running(self):
        with (
            patch.object(box_launcher, "port_open", return_value=False),
            patch.object(box_launcher, "_processes", return_value=[123]),
            patch.object(box_launcher, "_game_running", return_value=True),
        ):
            result = box_launcher.ensure_box(restart=True)

        self.assertFalse(result["ok"])
        self.assertEqual("needs_restart", result["action"])
        self.assertIn("炉石正在运行", result["message"])


if __name__ == "__main__":
    unittest.main()
