# -*- coding: utf-8 -*-
"""适配失败必须留痕。

线上实测：`choose_one_name_not_unique` 连续重试了 3090 次、最长空转 1 分半，
但日志里**一条推荐原文都没有**——因为 `[推荐]` 那行原来打在适配之后，适配一抛错
就什么都看不到，事后根本无法判断"盒子到底给了什么"。

推荐来源换成 JSON 之后同样锁住：适配抛错时，归一化指令（含卡名/目标/选项）
必须先打出来。
"""

import io
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace

from src.flow.recommendation_flow import FlowStepStatus, RecommendationFlow
from src.recommendation.mapper import payload_to_action
from src.safety.recommendation_validator import RecommendationValidator
from tests.support.recommendation_stubs import FakeSource, payload

PANEL = payload(
    "play_special",
    card={"ZONE_POSITION": 2, "cardId": "TIME_000", "cardName": "暮光侵扰"},
    target={"position": 1, "cardId": "X_001", "cardName": "死亡侍僧"},
    subOption={"cardId": "X_002", "cardName": "操纵荆棘"},
)


class ExplodingAdapter:
    """模拟适配层抛错（线上就是 RecommendationStateError 这一类）。"""

    def __call__(self, proposed, state):
        raise ValueError("boom: adapter rejected")


class FailureLoggingTests(unittest.TestCase):
    def run_step(self):
        active = SimpleNamespace(is_my_turn=True, game_num_turns_in_play=3)
        flow = RecommendationFlow(
            source=FakeSource(PANEL),
            mapper=payload_to_action,
            state_supplier=lambda: (active, 10),
            adapter=ExplodingAdapter(),
            validator=RecommendationValidator(),
            controller=SimpleNamespace(output=print),
            sleep=lambda _s: None)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            result = flow.run_player_turn_step()
        return result, buffer.getvalue()

    def test_recommendation_is_logged_before_a_failed_adapt(self):
        result, output = self.run_step()
        self.assertEqual(FlowStepStatus.RETRY, result.status)
        self.assertIn("[推荐]", output)
        # 归一化指令（动作 + 卡名 + 目标 + 选择卡牌 + 选项名）
        self.assertIn("暮光侵扰", output)
        self.assertIn("操纵荆棘", output)

    def test_logging_happens_even_though_the_adapter_raised(self):
        result, output = self.run_step()
        self.assertIn("boom: adapter rejected", result.diagnostics)
        self.assertNotEqual("", output.strip())


if __name__ == "__main__":
    unittest.main()
