# -*- coding: utf-8 -*-
"""版本号显示：唯一来源 + 三个出口（网页顶栏 / 浮窗品牌行 / CLI）。

背景：以前版本号在两处各写一份 —— `hsctl.py` 的 `HSCTL_VERSION = "1.0.0"` 和
`web_ui.Handler.server_version = "HSLegendArriver/1.0"`。两处改一处就会不一致，
而且界面上根本看不到，用户没法判断「手上这版是哪天的」。

本分支口径：**语义化版本**（`1.3.25`），界面显示 `v1.3.25`，后面不挂 git 短哈希。
（上游主线用的是发布日期 `2026.10.24`，两套口径 `update_check` 都认但互不比较。）
这里锁四件事：

1. `version.py` 是唯一来源，VERSION 必须是合法的 `X.Y.Z`；
2. CHANGELOG 最上面那条要是**今天**（防止发版忘了记）；
3. `/api/status` 与 `/api/version` 都带 version 字段，HTTP 头也统一；
4. 网页与浮窗的显示位真的存在（不是只改了后端）。
"""
from __future__ import annotations

import re
import unittest
from datetime import datetime
from pathlib import Path

import version

ROOT = Path(__file__).resolve().parent.parent


class VersionValueTests(unittest.TestCase):
    """VERSION 的取值口径：发布日期。"""

    def test_version_is_semver(self):
        parts = version.VERSION.split(".")
        self.assertEqual(3, len(parts), version.VERSION)
        self.assertTrue(all(p.isdigit() for p in parts), version.VERSION)
        # 不接受前导零（挡掉 1.03.25 这种手滑）
        self.assertTrue(all(str(int(p)) == p for p in parts), version.VERSION)

    def test_label_is_v_prefix_without_hash(self):
        label = version.version_label()
        self.assertEqual(f"v{version.VERSION}", label)
        # 用户明确要求：不要后面那串号码
        self.assertNotIn("+", label)

    def test_version_info_contract(self):
        info = version.version_info()
        self.assertEqual({"name", "version", "label"}, set(info))
        self.assertEqual(version.NAME, info["name"])
        self.assertEqual(version.VERSION, info["version"])
        self.assertEqual(version.version_label(), info["label"])

    def test_changelog_head_is_today(self):
        """发版时改 VERSION 容易忘：CHANGELOG 最上面那条应是今天的发布记录。"""
        text = (ROOT / "CHANGELOG.md").read_text(encoding="utf8")
        match = re.search(r"^\|\s*(\d{4})-(\d{2})-(\d{2})\s*\|", text, re.M)
        self.assertIsNotNone(match, "CHANGELOG 里找不到第一行日期")
        head = "-".join(match.groups())
        self.assertEqual(head, datetime.now().strftime("%Y-%m-%d"),
                         f"CHANGELOG 最新日期 {head} 不是今天：发版要补一条记录")


class StatusApiTests(unittest.TestCase):
    """网页拿得到版本（老后端没这个字段，前端要能优雅显示 v—）。"""

    def test_status_snapshot_carries_version(self):
        import web_ui

        snapshot = web_ui.status_snapshot()
        self.assertIn("version", snapshot)
        info = snapshot["version"]
        self.assertEqual(version.NAME, info["name"])
        self.assertEqual(version.VERSION, info["version"])
        self.assertEqual(version.version_label(), info["label"])

    def test_http_server_version_header_is_unified(self):
        import web_ui

        self.assertEqual(f"{version.NAME}/{version.VERSION}",
                         web_ui.Handler.server_version)


class SurfaceTests(unittest.TestCase):
    """网页顶栏与浮窗品牌行都要有真的显示位。"""

    def setUp(self):
        self.html = (ROOT / "web" / "index.html").read_text(encoding="utf8")

    def test_web_has_version_chip(self):
        self.assertIn('id="appVersion"', self.html)
        self.assertIn("ver-chip", self.html)

    def test_web_renders_version_from_status(self):
        self.assertIn("s.version", self.html)
        self.assertIn("v—", self.html, "没有版本字段时的占位符缺失")

    def test_overlay_brand_uses_version_module(self):
        import log_overlay

        self.assertEqual(version.NAME, log_overlay.BRAND_NAME)
        self.assertEqual(version.version_label(), log_overlay.VERSION_TEXT)

    def test_overlay_draws_version_label(self):
        src = (ROOT / "log_overlay.py").read_text(encoding="utf8")
        self.assertIn("text=VERSION_TEXT", src)
        # 品牌名左、版本号右，同一行。263px 宽里「居中品牌名 + 右下角版本」会
        # 叠在一起（实测把名字压成 "HSLegendAr"），所以锁住左右分栏的写法。
        # 格式化器可能把 .pack(...) 折成多行，断言前先归一化空白。
        flat = " ".join(src.split())
        self.assertIn('font=VERSION_FONT).pack( side="right"', flat)
        self.assertIn('side="left", padx=(px(10), 0)', src)

    def test_overlay_version_text_fits_brand_row(self):
        """浮窗不加宽，版本串必须短到能和品牌名同排。

        Georgia 13 bold 的 "HSLegendArriver" 在 150% 缩放下实测约 240px，
        品牌行整宽约 395px（263 设计值 ×1.5），扣掉两侧内边距只剩 ~365px。
        版本串按每字符 ~11px 估，超过 11 个字符就会压到品牌名。
        """
        import log_overlay

        self.assertLessEqual(len(log_overlay.VERSION_TEXT), 11,
                             "版本串太长，浮窗品牌行放不下")

    def test_cli_version_flag_uses_module(self):
        src = (ROOT / "hsctl.py").read_text(encoding="utf8")
        self.assertIn("version_label()", src)
        self.assertNotIn('HSCTL_VERSION = "1.0.0"', src,
                         "hsctl 里不该再有第二份写死的版本号")


if __name__ == "__main__":
    unittest.main()
