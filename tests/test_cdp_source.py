# -*- coding: utf-8 -*-
"""CDP 源的纯逻辑部分（不连真盒子）。"""

import unittest
from types import SimpleNamespace

from src.recommendation.cdp_source import CdpError, CdpRecommendationSource


def target(url, ws="ws://127.0.0.1:9222/devtools/page/1"):
    return {"id": "1", "url": url, "webSocketDebuggerUrl": ws,
            "type": "page"}


class PickTargetTests(unittest.TestCase):
    def setUp(self):
        self.source = CdpRecommendationSource()

    def test_prefers_the_in_game_panel(self):
        targets = [
            target("https://hs-web.lushi.163.com/client-home/"),
            target("https://hs-web-embed.lushi.163.com/client-jipaiqi/analysis"),
            target("https://hs-web-embed.lushi.163.com/client-jipaiqi/ladder-opp"),
        ]

        picked = self.source._pick_target(targets)

        self.assertIn("ladder-opp", picked["url"])

    def test_falls_back_to_any_embed_page(self):
        targets = [
            target("https://hs-web.lushi.163.com/client-home/"),
            target("https://hs-web-embed.lushi.163.com/client-jipaiqi/analysis"),
        ]

        picked = self.source._pick_target(targets)

        self.assertIn("client-jipaiqi", picked["url"])

    def test_falls_back_to_the_first_http_page(self):
        targets = [target("about:blank"), target("https://example.com/")]

        picked = self.source._pick_target(targets)

        self.assertEqual("https://example.com/", picked["url"])

    def test_no_page_raises(self):
        with self.assertRaises(CdpError):
            self.source._pick_target([])


class TargetSwitchTests(unittest.TestCase):
    """空闲时先连 analysis；进对局后 ladder-opp 出现要自动切过去。"""

    @staticmethod
    def _source(ws_url, targets):
        source = CdpRecommendationSource(target_check_interval=0.0)
        source._cdp = SimpleNamespace(close=lambda: None)
        source._ws_url = ws_url
        source._targets = lambda: targets
        return source

    def test_switches_when_a_better_page_appears(self):
        source = self._source("ws://analysis", [
            target("https://hs-web-embed.lushi.163.com/client-jipaiqi/analysis",
                   ws="ws://analysis"),
            target("https://hs-web-embed.lushi.163.com/client-jipaiqi/ladder-opp",
                   ws="ws://ladder"),
        ])

        source._refresh_target()

        self.assertIsNone(source._cdp)   # 已断开，下次 snapshot 会连到新页面

    def test_keeps_the_connection_when_the_best_page_is_unchanged(self):
        source = self._source("ws://analysis", [
            target("https://hs-web-embed.lushi.163.com/client-jipaiqi/analysis",
                   ws="ws://analysis"),
        ])

        source._refresh_target()

        self.assertIsNotNone(source._cdp)


class UnreachableTests(unittest.TestCase):
    def test_snapshot_returns_none_when_the_port_is_closed(self):
        source = CdpRecommendationSource(port=1, timeout=0.2)
        try:
            self.assertIsNone(source.snapshot())
            self.assertIsNotNone(source.last_error)
        finally:
            source.close()


if __name__ == "__main__":
    unittest.main()
