"""HSAng 时间线提示「回溯/维持」的解析、适配、点击与 flow 防重试测试。

回溯/维持只影响 HSAng 侧 UI、不改动 Power.log，所以 flow 必须对这两种动作
特判：面板没变时返回 WAITING（等待盒子更新）而不是 RETRY（会二次撤销/误点）。
"""

import unittest
from contextlib import nullcontext
from types import SimpleNamespace

from manual_controller import (
    ActionExecutionResult,
    ClickExecutor,
    ManualController,
    TimelineAction,
)
from src.flow.recommendation_flow import FlowStepStatus, RecommendationFlow
from src.game_state.recommendation_adapter import adapt_action
from tests.support.recommendation_parser import (
    RecommendationParseError,
    RecommendationParser,
)
from src.recommendation_models import (
    ActionKind,
)
from src.safety.recommendation_validator import RecommendationValidator


class TimelineParserTests(unittest.TestCase):
    def setUp(self):
        self.parser = RecommendationParser()

    def _ocr(self, instruction):
        return SimpleNamespace(
            frame_id="frame-1",
            normalized_text=instruction,
            confidence=0.99,
        )

    def _parse(self, instruction):
        return self.parser.parse(
            self._ocr(instruction), turn_number=3, log_revision=7)

    def test_undo_literal_parses_to_timeline_undo(self):
        for text in ("回溯", "打法参考A\n回溯"):
            with self.subTest(text=text):
                proposed = self._parse(text)
                self.assertEqual(ActionKind.TIMELINE_UNDO, proposed.action)
                self.assertEqual("回溯", proposed.normalized_instruction)

    def test_keep_literal_parses_to_timeline_keep(self):
        proposed = self._parse("维持")

        self.assertEqual(ActionKind.TIMELINE_KEEP, proposed.action)
        self.assertEqual("维持", proposed.normalized_instruction)

    def test_suffixed_button_labels_parse_to_timeline_action(self):
        # 追加字常是带标题的按钮文案「回溯时间线/维持时间线」，也可能 OCR 把
        # 空白也读进同一行（「回溯 时间线」），或把「时间线」读成单独一行（该行
        # 非动作行会被过滤，只剩「回溯」）。
        for text, expected in (
                ("回溯时间线", ActionKind.TIMELINE_UNDO),
                ("回溯 时间线", ActionKind.TIMELINE_UNDO),
                ("回溯\n时间线", ActionKind.TIMELINE_UNDO),
                ("维持时间线", ActionKind.TIMELINE_KEEP),
                ("打法参考A\n回溯时间线", ActionKind.TIMELINE_UNDO)):
            with self.subTest(text=text):
                proposed = self._parse(text)
                self.assertEqual(expected, proposed.action)

    def test_timeline_coexists_with_the_pending_play_line(self):
        # 弹框时上一句「打出N号位随从」还挂着、旁边带一行时间线字：
        # 那张卡上一步已打出并消费，这次只点时间线按钮，不再执行打出。
        for text, expected in (("打出1号位随从\n维持", ActionKind.TIMELINE_KEEP),
                               ("打出1号位随从\n回溯", ActionKind.TIMELINE_UNDO)):
            with self.subTest(text=text):
                proposed = self._parse(text)
                self.assertEqual(expected, proposed.action)

    def test_timeline_coexists_with_pending_discover_hand_pick(self):
        # 战吼打完、手牌目标选择（如「选择我方2号位卡牌」）也已完成，但该句仍挂
        # 在面板上、旁边再追加「回溯时间线」——此刻点回溯按钮、不再重选。
        for text, expected in (
                ("选择我方2号位卡牌\n回溯时间线", ActionKind.TIMELINE_UNDO),
                ("选择我方2号位卡牌\n维持", ActionKind.TIMELINE_KEEP)):
            with self.subTest(text=text):
                proposed = self._parse(text)
                self.assertEqual(expected, proposed.action)

    def test_timeline_word_beats_any_coexisting_content(self):
        # 盒子在特效完成后把时间线字追加在残留推荐旁；弹框模态，点按钮前什么都
        # 做不了，所以共存内容一律忽略：出现回溯点回溯、出现维持点维持。
        for text, expected in (
                ("结束回合\n维持", ActionKind.TIMELINE_KEEP),
                ("回溯\n锻造2号位卡牌", ActionKind.TIMELINE_UNDO),
                ("维持\n打出1号位随从\n打出2号位随从",
                 ActionKind.TIMELINE_KEEP),
                ("使用英雄技能\n回溯", ActionKind.TIMELINE_UNDO),
                ("替换1号位卡牌\n回溯时间线", ActionKind.TIMELINE_UNDO)):
            with self.subTest(text=text):
                self.assertEqual(expected, self._parse(text).action)

    def test_undo_and_keep_shown_together_is_ambiguous(self):
        # 回溯/维持同屏无法判定该点哪个，报歧义走重试、绝不猜。
        for text in ("回溯\n维持", "回溯时间线\n维持", "回溯\n维持时间线"):
            with self.subTest(text=text):
                with self.assertRaisesRegex(
                        RecommendationParseError, "ambiguous_actions"):
                    self._parse(text)


class TimelineAdapterTests(unittest.TestCase):
    @staticmethod
    def _proposed(action_kind):
        text = {ActionKind.TIMELINE_UNDO: "回溯",
                ActionKind.TIMELINE_KEEP: "维持"}[action_kind]
        ocr = SimpleNamespace(
            frame_id="frame-1",
            normalized_text=text,
            confidence=0.99,
        )
        return RecommendationParser().parse(
            ocr, turn_number=3, log_revision=7)

    def _state(self):
        return SimpleNamespace(game_num_turns_in_play=3, is_my_turn=True)

    def test_undo_maps_to_timeline_action(self):
        adapted = adapt_action(
            self._proposed(ActionKind.TIMELINE_UNDO), self._state())

        self.assertIsInstance(adapted.manual_action, TimelineAction)
        self.assertEqual("undo", adapted.manual_action.choice)
        self.assertEqual("timeline_clicked", adapted.postcondition)
        self.assertIsNone(adapted.source_entity_id)
        self.assertIsNone(adapted.target_entity_id)

    def test_keep_maps_to_timeline_action(self):
        adapted = adapt_action(
            self._proposed(ActionKind.TIMELINE_KEEP), self._state())

        self.assertIsInstance(adapted.manual_action, TimelineAction)
        self.assertEqual("keep", adapted.manual_action.choice)
        self.assertEqual("timeline_clicked", adapted.postcondition)


class RecordingClickModule:
    def __init__(self):
        self.events = []

    def click_timeline_undo(self):
        self.events.append(("timeline_undo",))

    def click_timeline_keep(self):
        self.events.append(("timeline_keep",))


class TimelineControllerTests(unittest.TestCase):
    @staticmethod
    def _controller(clicks, sleeps):
        return ManualController(
            output_func=lambda _message: None,
            executor=ClickExecutor(
                click_module=clicks,
                sleep_func=sleeps.append,
                action_context=nullcontext,
            ),
        )

    def _state(self):
        return SimpleNamespace(is_my_turn=True, game_num_turns_in_play=3)

    def test_undo_click_executes_undo(self):
        clicks = RecordingClickModule()
        sleeps = []

        result = self._controller(clicks, sleeps).execute(
            TimelineAction("undo"), self._state())

        self.assertTrue(result.executed, result.message)
        self.assertIn("回溯", result.message)
        self.assertEqual([("timeline_undo",)], clicks.events)
        self.assertEqual([], sleeps)

    def test_keep_click_executes_keep(self):
        clicks = RecordingClickModule()
        sleeps = []

        result = self._controller(clicks, sleeps).execute(
            TimelineAction("keep"), self._state())

        self.assertTrue(result.executed, result.message)
        self.assertIn("维持", result.message)
        self.assertEqual([("timeline_keep",)], clicks.events)

    def test_unknown_choice_is_rejected_before_any_click(self):
        clicks = RecordingClickModule()
        sleeps = []

        result = self._controller(clicks, sleeps).execute(
            TimelineAction("rewind"), self._state())

        self.assertFalse(result.executed)
        self.assertEqual([], clicks.events)
        self.assertEqual([], sleeps)

    def test_not_my_turn_is_rejected_before_any_click(self):
        clicks = RecordingClickModule()
        sleeps = []

        result = self._controller(clicks, sleeps).execute(
            TimelineAction("undo"),
            SimpleNamespace(is_my_turn=False, game_num_turns_in_play=3))

        self.assertFalse(result.executed)
        self.assertEqual([], clicks.events)


class RecordingController:
    def __init__(self):
        self.actions = []

    def execute(self, action, _state):
        self.actions.append(action)
        return ActionExecutionResult(True, "executed")


class TimelineFlowTests(unittest.TestCase):
    def _step(self, action_name, *, bump_after=None):
        from src.recommendation.mapper import payload_to_action
        from tests.support.recommendation_stubs import FakeSource, payload

        active = SimpleNamespace(
            is_my_turn=True, game_num_turns_in_play=3, hand_entry_count=0)
        controller = RecordingController()
        source = FakeSource(payload(action_name), bump_after=bump_after)
        flow = RecommendationFlow(
            source=source,
            mapper=payload_to_action,
            state_supplier=lambda: (active, 10),
            adapter=adapt_action,
            validator=RecommendationValidator(),
            controller=controller,
            result_timeout=0.0,
        )
        return flow, controller, source

    def test_unchanged_panel_waits_instead_of_retrying(self):
        flow, controller, _source = self._step("timeline_undo")

        result = flow.run_player_turn_step()

        # 点完面板没变、Power.log 也没变：绝不能 RETRY（会二次撤销），
        # 应标记已消费并等待盒子更新下一条推荐。
        self.assertEqual(FlowStepStatus.OBSERVE, result.status)
        self.assertIn("waiting_recommendation_update", result.diagnostics)
        self.assertEqual([TimelineAction("undo")], controller.actions)

    def test_identical_recommendation_is_not_executed_twice(self):
        flow, controller, _source = self._step("timeline_undo")

        first = flow.run_player_turn_step()
        second = flow.run_player_turn_step()

        # 同一条推送只点一次；第二次直接等待盒子更新。
        self.assertEqual(FlowStepStatus.OBSERVE, first.status)
        self.assertEqual(FlowStepStatus.OBSERVE, second.status)
        self.assertIn("waiting_recommendation_update", second.diagnostics)
        self.assertEqual([TimelineAction("undo")], controller.actions)

    def test_keep_choice_also_waits_after_single_click(self):
        flow, controller, _source = self._step("timeline_keep")

        result = flow.run_player_turn_step()

        self.assertEqual(FlowStepStatus.OBSERVE, result.status)
        self.assertIn("waiting_recommendation_update", result.diagnostics)
        self.assertEqual([TimelineAction("keep")], controller.actions)

    def test_undo_then_keep_each_execute_once(self):
        flow, controller, source = self._step("timeline_undo", bump_after=2)

        first = flow.run_player_turn_step()
        source.push(payload_for_keep())
        second = flow.run_player_turn_step()

        self.assertEqual(FlowStepStatus.EXECUTED, first.status)
        self.assertEqual(FlowStepStatus.OBSERVE, second.status)
        self.assertEqual(
            [TimelineAction("undo"), TimelineAction("keep")],
            controller.actions)


def payload_for_keep():
    from tests.support.recommendation_stubs import payload
    return payload("timeline_keep")


if __name__ == "__main__":
    unittest.main()
