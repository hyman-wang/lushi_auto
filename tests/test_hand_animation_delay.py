import time
import unittest
from types import SimpleNamespace

from manual_controller import ActionExecutionResult
from src.flow.recommendation_flow import FlowStepStatus, RecommendationFlow
from src.game_state.recommendation_adapter import adapt_action
from src.recommendation.mapper import payload_to_action
from src.safety.recommendation_validator import RecommendationValidator
from tests.support.recommendation_stubs import FakeSource, payload


class FakeClock:
    def __init__(self, now=10.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class HandAnimationDelayTests(unittest.TestCase):
    def test_flow_uses_monotonic_clock_by_default(self):
        flow = RecommendationFlow(
            source=None,
            mapper=None,
            state_supplier=None,
            adapter=None,
            validator=None,
            controller=None,
        )

        self.assertIs(time.monotonic, flow.clock)
        self.assertIs(time.monotonic, flow.hand_animation_delay.clock)

    def test_each_new_hand_entity_extends_deadline_by_one_second(self):
        from src.flow.hand_animation_delay import HandAnimationDelay

        clock = FakeClock()
        delay = HandAnimationDelay(clock=clock)

        delay.observe(20)
        self.assertEqual(0.0, delay.remaining())

        delay.observe(22)
        self.assertAlmostEqual(2.0, delay.remaining())

        clock.advance(0.4)
        delay.observe(23)
        self.assertAlmostEqual(2.6, delay.remaining())

    def test_counter_reset_clears_previous_game_deadline(self):
        from src.flow.hand_animation_delay import HandAnimationDelay

        clock = FakeClock()
        delay = HandAnimationDelay(clock=clock)
        delay.observe(10)
        delay.observe(11)
        self.assertAlmostEqual(1.0, delay.remaining())

        delay.observe(0)

        self.assertEqual(0.0, delay.remaining())

    def test_flow_waits_one_second_per_new_hand_entity_before_clicking(self):
        clock = FakeClock()
        active = SimpleNamespace(
            is_my_turn=True,
            game_num_turns_in_play=3,
            my_hand_cards=[],
            hand_entry_count=12,
        )
        events = []

        def sleep(seconds):
            if seconds > 0:
                events.append(("sleep", seconds))
            clock.advance(seconds)

        class Controller:
            @staticmethod
            def execute(_action, _state):
                events.append(("execute",))
                return ActionExecutionResult(True, "executed")

        flow = RecommendationFlow(
            source=FakeSource(payload("end_turn"), bump_after=2),
            mapper=payload_to_action,
            state_supplier=lambda: (active, 10),
            adapter=adapt_action,
            validator=RecommendationValidator(),
            controller=Controller(),
            sleep=sleep,
            clock=clock,
        )

        # 第一次 observe 是历史基线；之后多出来的 2 张牌各等 1 秒。
        flow.hand_animation_delay.observe(10)

        result = flow.run_player_turn_step()

        self.assertEqual(FlowStepStatus.EXECUTED, result.status)
        self.assertEqual([("sleep", 2.0), ("execute",)], events)

    def test_draws_detected_while_waiting_extend_the_delay(self):
        from src.flow.hand_animation_delay import HandAnimationDelay

        clock = FakeClock()
        delay = HandAnimationDelay(clock=clock)
        delay.observe(30)
        first_draw = SimpleNamespace(
            my_hand_cards=[], hand_entry_count=31)
        second_draw = SimpleNamespace(
            my_hand_cards=[], hand_entry_count=32)
        states = iter((
            (first_draw, 10),
            (second_draw, 11),
            (second_draw, 11),
        ))
        sleeps = []

        def sleep(seconds):
            sleeps.append(seconds)
            clock.advance(seconds)

        flow = object.__new__(RecommendationFlow)
        flow.state_supplier = lambda: next(states)
        flow.hand_animation_delay = delay
        flow.sleep = sleep

        fresh_state, fresh_revision = flow._wait_for_hand_animation()

        self.assertIs(second_draw, fresh_state)
        self.assertEqual(11, fresh_revision)
        self.assertEqual([1.0, 1.0], sleeps)


if __name__ == "__main__":
    unittest.main()
