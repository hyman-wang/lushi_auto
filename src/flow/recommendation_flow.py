"""Execute exactly one validated recommendation and verify its result.

推荐来源已经换成盒子 CEF 页面推送的 JSON（``CdpRecommendationSource``），
不再截图/OCR：

  * ``source.snapshot()`` 给出最新的 ``RecommendationSnapshot``
    （``version`` = 盒子推送的毫秒时间戳，用来判断"有没有新推荐"）。
  * ``mapper`` 把 payload 映射成 ``ProposedAction``。
  * 执行前后都用 ``version`` 是否变化来判断推荐有没有更新，
    替代原来的"比较 OCR 文本 / 截图哈希"。
"""

from dataclasses import dataclass
from enum import Enum
import inspect
import time

from src.flow.hand_animation_delay import HandAnimationDelay
from src.recommendation_models import ActionKind
from src.safety.recommendation_validator import ConsumedActionStore


# 「回合号还没记录过」的哨兵：不能用 None，因为有些状态里回合号就是 None。
_UNSET_TURN = object()


def _accepts_action_kind(hook) -> bool:
    """挂点是否接受 action_kind 参数（老挂点只接受 0 个参数）。

    按函数签名判断，而不是靠 TypeError 兜底——挂点内部真正的 TypeError 会被
    误当成“参数不对”，反而把错误吞掉。
    """
    try:
        parameters = inspect.signature(hook).parameters
    except (TypeError, ValueError):
        return False
    for parameter in parameters.values():
        if parameter.kind in (inspect.Parameter.POSITIONAL_ONLY,
                              inspect.Parameter.POSITIONAL_OR_KEYWORD,
                              inspect.Parameter.VAR_POSITIONAL):
            return True
    return False


class FlowStepStatus(str, Enum):
    EXECUTED = "executed"
    OBSERVE = "observe"
    RETRY = "retry"


class ResultStatus(str, Enum):
    COMPLETED = "completed"
    WAITING_RECOMMENDATION = "waiting_recommendation"
    RETRY = "retry"


@dataclass(frozen=True)
class FlowStepResult:
    status: FlowStepStatus
    diagnostics: str = ""


class RecommendationFlow:
    def __init__(self, source, mapper, state_supplier, adapter,
                 validator, controller, sleep=time.sleep,
                 clock=time.monotonic,
                 result_timeout=3.0, stopped=lambda: False,
                 consumed=None, post_action_delay=0.0,
                 post_action_pause=None,
                 hand_animation_delay=None,
                 draw_extra_delay_per_card=0.0):
        self.source = source
        self.mapper = mapper
        self.state_supplier = state_supplier
        self.adapter = adapter
        self.validator = validator
        self.controller = controller
        self.sleep = sleep
        self.clock = clock
        # 执行完动作后等盒子推下一条推荐的最长时间（秒）。
        self.result_timeout = result_timeout
        self.stopped = stopped
        self.consumed = consumed or ConsumedActionStore()
        self.post_action_delay = post_action_delay
        # 「活人感」（可选）：盒子意见执行完后的随机延时 + 鼠标悬停。
        # 返回 True 表示已接管本次延时，就不再叠加固定的 post_action_delay。
        self.post_action_pause = post_action_pause
        # 挂点是否接受 action_kind（新挂点会据此决定“看手牌”还是“看场面”）。
        self._pause_takes_action_kind = (
            post_action_pause is not None
            and _accepts_action_kind(post_action_pause))
        # 「抽牌额外延时」（秒/张，网页「延时设置」可调）。
        self.draw_extra_delay_per_card = float(draw_extra_delay_per_card or 0.0)
        self._seen_entry_count = None
        self._entry_turn = _UNSET_TURN
        self._entry_turn_exempt_used = False
        self._acted_this_turn = False
        self.hand_animation_delay = (
            hand_animation_delay
            if hand_animation_delay is not None
            else HandAnimationDelay(clock=clock))
        # 已经执行过的推送版本：同一条推荐不重复点。
        self._executed_version = None
        # 最近一次成功读到的版本（诊断/日志用）。
        self.last_version = None
        self.last_error = None
        self.waiting_instruction = None
        self.waiting_turn_number = None
        self.waiting_action_kind = None

    # ------------------------------------------------------------------ 主流程
    def run_player_turn_step(self):
        try:
            state, revision = self.state_supplier()
            self.hand_animation_delay.observe(
                getattr(state, "hand_entry_count", 0))
            self._account_hand_entries(state)
            if not state.is_my_turn:
                return FlowStepResult(FlowStepStatus.OBSERVE, "opponent_turn")

            snapshot = self.source.snapshot()
            if snapshot is None:
                self.last_error = getattr(self.source, "last_error", None)
                return FlowStepResult(
                    FlowStepStatus.RETRY, "recommendation_source_unavailable")
            self.last_version = snapshot.version
            self.last_error = None

            if snapshot.version == self._executed_version:
                return FlowStepResult(
                    FlowStepStatus.OBSERVE, "waiting_recommendation_update")

            try:
                proposed = self.mapper(
                    snapshot.payload,
                    turn_number=state.game_num_turns_in_play,
                    log_revision=revision,
                    frame_id="cdp-%d" % snapshot.version)
            except Exception as exc:
                # 不支持的动作（泰坦/星舰等）不点，等盒子推下一条。
                code = getattr(exc, "code", type(exc).__name__)
                print(f"[推荐] 跳过不支持的动作：{code}")
                return FlowStepResult(
                    FlowStepStatus.OBSERVE,
                    f"recommendation_unsupported:{code}")

            if proposed.turn_number != state.game_num_turns_in_play:
                return FlowStepResult(FlowStepStatus.RETRY, "turn_changed")

            print(f"[推荐] {proposed.normalized_instruction}")
            if proposed.action == ActionKind.MULLIGAN:
                return FlowStepResult(
                    FlowStepStatus.OBSERVE, "stale_mulligan_recommendation")

            adapted = self.adapter(proposed, state)
            fresh_state, fresh_revision = self._wait_for_hand_animation()

            current = self.source.snapshot()
            if current is None or current.version != snapshot.version:
                return FlowStepResult(
                    FlowStepStatus.RETRY, "recommendation_changed")

            validation = self.validator.validate(
                proposed, adapted, fresh_state, fresh_revision,
                "PLAYER_TURN", self.consumed, self.stopped(),
                snapshot_version=snapshot.version)
            if not validation.accepted:
                return FlowStepResult(FlowStepStatus.RETRY, validation.code)
            adapted, key = validation.value

            print("[执行] 开始点击。")
            result = self.controller.execute(adapted.manual_action, fresh_state)
            if not result.executed or result.recovery_needed:
                return FlowStepResult(FlowStepStatus.RETRY,
                                      "execution_failed")
            # 同一条推荐只执行一次（盒子推送版本是幂等键）。
            self._executed_version = snapshot.version
            self._acted_this_turn = True

            # 操作结束后再读下一条推荐（盒子更新面板需要时间）。
            paused = False
            if self.post_action_pause is not None:
                try:
                    if self._pause_takes_action_kind:
                        paused = bool(self.post_action_pause(proposed.action))
                    else:
                        paused = bool(self.post_action_pause())
                except Exception:
                    paused = False
            if not paused and self.post_action_delay:
                output = getattr(self.controller, "output", None)
                if output is not None:
                    try:
                        output(
                            f"[SYS] 操作结束，延时 "
                            f"{self.post_action_delay:.1f}s 后继续")
                    except Exception:
                        pass
                self.sleep(self.post_action_delay)
            if self.draw_extra_delay_per_card > 0:
                self._account_hand_entries(self.state_supplier()[0])

            verified = self._verify_result(
                proposed, adapted, snapshot.version, fresh_state, fresh_revision)
            if verified == ResultStatus.COMPLETED:
                self.consumed.mark_consumed(key)
                return FlowStepResult(FlowStepStatus.EXECUTED)
            if verified == ResultStatus.WAITING_RECOMMENDATION:
                if proposed.action != ActionKind.CHOOSE_DISCOVER:
                    self.consumed.mark_consumed(key)
                self.waiting_instruction = proposed.normalized_instruction
                self.waiting_turn_number = proposed.turn_number
                self.waiting_action_kind = proposed.action
                return FlowStepResult(
                    FlowStepStatus.OBSERVE,
                    "waiting_recommendation_update")
            return FlowStepResult(
                FlowStepStatus.RETRY, "result_not_confirmed")
        except Exception as exc:
            return FlowStepResult(
                FlowStepStatus.RETRY,
                f"{type(exc).__name__}:{exc}")

    # ------------------------------------------------------------------ 辅助
    def _wait_for_hand_animation(self):
        """等待手牌入场动画完成，再取最新状态做校验。"""
        while True:
            state, revision = self.state_supplier()
            self.hand_animation_delay.observe(
                getattr(state, "hand_entry_count", 0))
            remaining = self.hand_animation_delay.remaining()
            if remaining <= 0:
                return state, revision
            self.sleep(remaining)

    def _wait_for_new_recommendation(self, version, timeout):
        """等盒子推一条比 ``version`` 新的推荐；超时返回 False。"""
        deadline = self.clock() + max(0.0, timeout)
        while True:
            current = self.source.snapshot()
            if current is not None and current.version > version:
                self.last_version = current.version
                return True
            if self.clock() >= deadline:
                return False
            self.sleep(0.2)

    def _verify_result(self, proposed, adapted, version, before_state,
                       before_revision):
        """执行后确认结果。

        首选信号是盒子推了新推荐（version 变大）；没有推送时退回
        Power.log 后置条件（换回合 / 手牌变化等）。
        """
        if self._wait_for_new_recommendation(version, self.result_timeout):
            return ResultStatus.COMPLETED
        after_state, after_revision = self.state_supplier()
        log_changed = (after_revision > before_revision
                       and self._postcondition(
                           adapted.postcondition, before_state, after_state,
                           adapted.source_entity_id,
                           adapted.target_entity_id))
        if (proposed.action == ActionKind.END_TURN
                and after_state.game_num_turns_in_play
                != before_state.game_num_turns_in_play):
            return ResultStatus.COMPLETED
        if proposed.action in (ActionKind.TIMELINE_UNDO,
                               ActionKind.TIMELINE_KEEP):
            return ResultStatus.WAITING_RECOMMENDATION
        if proposed.action == ActionKind.CHOOSE_DISCOVER:
            return ResultStatus.WAITING_RECOMMENDATION
        if log_changed:
            return ResultStatus.WAITING_RECOMMENDATION
        return ResultStatus.RETRY

    def _clear_waiting(self):
        self.waiting_instruction = None
        self.waiting_turn_number = None
        self.waiting_action_kind = None

    # -------------------------------------------------- 抽牌额外延时（回合内抽牌）
    @staticmethod
    def _hand_entry_count(state):
        """手牌入场计数（Power.log 里 ZONE→HAND 的累计次数）。"""
        try:
            return int(getattr(state, "hand_entry_count", 0) or 0)
        except (TypeError, ValueError):
            return 0

    def _account_hand_entries(self, state):
        """我方回合手牌变多 = 抽到牌 → 每张追加「抽牌额外延时」。

        规则（按需求）：
          * 每回合开始那一下的常规抽 1 张不算（本回合我方还没动作过时让掉 1 张）；
          * 同一回合里再多抽的（开局一次抽 2 张）算；
          * 回合内任何操作触发的抽牌，每张都算。
        对手回合的抽牌不归我们延时；换局导致计数清零时重新开始记账。
        该功能关闭（0 秒/张）时直接不记账。
        """
        if self.draw_extra_delay_per_card <= 0:
            return 0
        count = self._hand_entry_count(state)
        previous = self._seen_entry_count
        self._seen_entry_count = count

        turn = getattr(state, "game_num_turns_in_play", None)
        if self._entry_turn is _UNSET_TURN or turn != self._entry_turn:
            self._entry_turn = turn
            self._entry_turn_exempt_used = False
            self._acted_this_turn = False

        if previous is None or count == previous:
            return 0
        if count < previous:                     # 换局/计数清零
            return 0
        if not getattr(state, "is_my_turn", False):
            return 0

        gained = count - previous
        if not self._entry_turn_exempt_used and not self._acted_this_turn:
            # 我方本回合还没动作过 → 这次增加是回合开始的常规抽牌，让掉 1 张。
            self._entry_turn_exempt_used = True
            gained -= 1
        if gained <= 0:
            return 0
        extra = gained * self.draw_extra_delay_per_card
        if extra <= 0:
            return gained
        self._announce(f"[SYS] 抽到 {gained} 张牌，额外延时 {extra:.1f}s 后继续")
        self.sleep(extra)
        return gained

    def _announce(self, text):
        """把延时说明打到控制台与浮窗（浮窗按「延时」关键字收）。"""
        output = getattr(self.controller, "output", None)
        if output is not None:
            try:
                output(text)
            except Exception:
                pass
            return
        try:
            print(text)
        except Exception:
            pass

    @staticmethod
    def _postcondition(kind, before, after, source_entity_id=None,
                       target_entity_id=None):
        if kind == "turn_changed":
            return (after.game_num_turns_in_play != before.game_num_turns_in_play
                    or not after.is_my_turn)
        if kind == "hand_card_left":
            return source_entity_id not in {
                getattr(card, "entity_id", None)
                for card in after.my_hand_cards}
        if kind == "hero_power_changed":
            return (getattr(after.my_hero_power, "exhausted", 0)
                    != getattr(before.my_hero_power, "exhausted", 0)
                    or after.my_last_mana != before.my_last_mana)
        if kind == "choice_resolved":
            if (getattr(before, "discover_choice_count", None) in (1, 2, 3, 4)
                    and getattr(after, "discover_choice_count", None) is None):
                return True
            before_hand = tuple(
                getattr(card, "entity_id", None)
                for card in before.my_hand_cards)
            after_hand = tuple(
                getattr(card, "entity_id", None)
                for card in after.my_hand_cards)
            return before_hand != after_hand
        if kind == "location_changed":
            old = RecommendationFlow._entity_by_id(
                before.my_locations, source_entity_id)
            new = RecommendationFlow._entity_by_id(
                after.my_locations, source_entity_id)
            return new is None or (
                getattr(new, "action_cooldown", 0)
                != getattr(old, "action_cooldown", 0)
                or getattr(new, "damage", 0) != getattr(old, "damage", 0))
        if kind == "starship_launched":
            old = RecommendationFlow._entity_by_id(
                before.my_minions, source_entity_id)
            new = RecommendationFlow._entity_by_id(
                after.my_minions, source_entity_id)
            return old is not None and (
                new is None
                or getattr(new, "card_id", None)
                != getattr(old, "card_id", None))
        if kind == "combat_state_changed":
            old_source = RecommendationFlow._entity_by_id(
                before.my_minions, source_entity_id)
            new_source = RecommendationFlow._entity_by_id(
                after.my_minions, source_entity_id)
            old_target = RecommendationFlow._entity_by_id(
                before.oppo_minions, target_entity_id)
            new_target = RecommendationFlow._entity_by_id(
                after.oppo_minions, target_entity_id)
            return (new_source is None or new_target is None
                    or getattr(new_source, "exhausted", 0)
                    != getattr(old_source, "exhausted", 0)
                    or getattr(new_target, "damage", 0)
                    != getattr(old_target, "damage", 0))
        if kind == "hero_combat_state_changed":
            old_hero = getattr(before, "my_hero", None)
            new_hero = getattr(after, "my_hero", None)
            old_target = RecommendationFlow._entity_by_id(
                before.oppo_minions, target_entity_id)
            new_target = RecommendationFlow._entity_by_id(
                after.oppo_minions, target_entity_id)
            return (new_hero is None or new_target is None
                    or getattr(new_hero, "exhausted", 0)
                    != getattr(old_hero, "exhausted", 0)
                    or getattr(new_hero, "damage", 0)
                    != getattr(old_hero, "damage", 0)
                    or getattr(new_target, "damage", 0)
                    != getattr(old_target, "damage", 0))
        return False

    @staticmethod
    def _entity_by_id(collection, entity_id):
        return next((entity for entity in collection
                     if getattr(entity, "entity_id", None) == entity_id), None)
