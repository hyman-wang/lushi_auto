# -*- coding: utf-8 -*-
"""状态接口里的「实时进度」字段：第几回合、是否我方回合、最近一条日志。

网页状态卡直接显示这三项，用来回答"现在到底在干什么"。字段缺失或游戏没开时
必须是 0 / False / None，不能让 /api/status 抛错。
"""
import unittest

import web_ui


class ProgressFieldsTests(unittest.TestCase):
    def test_snapshot_always_carries_progress_fields(self):
        snap = web_ui.status_snapshot()

        self.assertIn("turn", snap)
        self.assertIn("my_turn", snap)
        self.assertIn("last_log", snap)
        self.assertIsInstance(snap["turn"], int)
        self.assertIsInstance(snap["my_turn"], bool)
        self.assertGreaterEqual(snap["turn"], 0)

    def test_last_log_shape(self):
        web_ui._log("SYS", "状态字段自测")
        entry = web_ui.status_snapshot()["last_log"]

        self.assertIsNotNone(entry)
        self.assertEqual({"level", "msg", "t"}, set(entry))
        self.assertEqual("状态字段自测", entry["msg"])

    def test_progress_is_quiet_when_idle(self):
        """没在跑自动化时不给回合数，避免把上一局的残留当成当前进度。"""
        snap = web_ui.status_snapshot()
        if not snap["running"]:
            self.assertEqual(0, snap["turn"])
            self.assertFalse(snap["my_turn"])


if __name__ == "__main__":
    unittest.main()
