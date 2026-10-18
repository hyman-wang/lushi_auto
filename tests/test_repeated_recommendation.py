import unittest
from types import SimpleNamespace

from manual_controller import ActionExecutionResult, EndTurnAction
from src.flow.recommendation_flow import FlowStepStatus, RecommendationFlow
from src.game_state.recommendation_adapter import adapt_action
from src.recommendation.mapper import payload_to_action
from src.safety.recommendation_validator import RecommendationValidator
from tests.support.recommendation_stubs import FakeSource, payload


class RecordingController:
    def __init__(self):
        self.actions = []

    def execute(self, action, _state):
        self.actions.append(action)
        return ActionExecutionResult(True, "executed")


def active_state(turn=3):
    return SimpleNamespace(
        is_my_turn=True, game_num_turns_in_play=turn, hand_entry_count=0)


class RepeatedRecommendationTests(unittest.TestCase):
    def test_recommendation_executes_when_the_box_pushes_a_new_one(self):
        # 第 3 次 snapshot()（执行后的确认阶段）盒子推了新推荐 → 动作算完成。
        flow = RecommendationFlow(
            source=FakeSource(payload("end_turn"), bump_after=2),
            mapper=payload_to_action,
            state_supplier=lambda: (active_state(), 10),
            adapter=adapt_action,
            validator=RecommendationValidator(),
            controller=(controller := RecordingController()),
        )

        result = flow.run_player_turn_step()

        self.assertEqual(FlowStepStatus.EXECUTED, result.status)
        self.assertEqual(1, len(controller.actions))
        self.assertIsInstance(controller.actions[0], EndTurnAction)

    def test_same_push_is_not_executed_twice(self):
        # 盒子没推新推荐：动作只点一次，下一次 step 直接等待，不重复点。
        flow = RecommendationFlow(
            source=FakeSource(payload("end_turn")),
            mapper=payload_to_action,
            state_supplier=lambda: (active_state(), 10),
            adapter=adapt_action,
            validator=RecommendationValidator(),
            controller=(controller := RecordingController()),
            result_timeout=0.0,
        )

        first = flow.run_player_turn_step()
        second = flow.run_player_turn_step()

        self.assertEqual(FlowStepStatus.RETRY, first.status)
        self.assertIn("result_not_confirmed", first.diagnostics)
        self.assertEqual(FlowStepStatus.OBSERVE, second.status)
        self.assertIn("waiting_recommendation_update", second.diagnostics)
        self.assertEqual(1, len(controller.actions))


if __name__ == "__main__":
    unittest.main()
