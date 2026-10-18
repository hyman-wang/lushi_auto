"""Validate a recommendation immediately before execution.

推荐来源是盒子 CEF 推送的结构化 JSON（见 ``src/recommendation/cdp_source.py``），
不再有截图/OCR，所以原来的帧哈希、DPI、前景窗口、面板可见性这些检查全部去掉；
取而代之的是：
  * 回合号 / 日志版本号必须和当前状态一致（防止拿着旧推荐点）；
  * 同一条推送（``snapshot_version``）只能消费一次；
  * 必须是我方回合、流程处于 PLAYER_TURN、没有停止。
"""

from src.recommendation_models import ValidationResult


class ConsumedActionStore:
    def __init__(self):
        self._keys = set()

    @staticmethod
    def key_for(proposed, adapted):
        return (
            proposed.turn_number, proposed.log_revision,
            proposed.normalized_instruction, adapted.source_entity_id,
            adapted.target_entity_id,
        )

    def contains(self, key):
        return key in self._keys

    def mark_consumed(self, key):
        self._keys.add(key)


class RecommendationValidator:
    def __init__(self, config=None):
        # config 保留参数位：老调用方仍会传 RecommendationConfig。
        self.config = config

    def validate(self, proposed, adapted, state, log_revision,
                 flow_state, consumed, stopped, snapshot_version=None):
        if proposed.turn_number != state.game_num_turns_in_play:
            return ValidationResult.reject("turn_changed")
        if proposed.log_revision != log_revision:
            return ValidationResult.reject("revision_changed")
        if proposed.semantic_confidence < 1.0:
            return ValidationResult.reject("semantic_confidence")
        if not getattr(state, "is_my_turn", False):
            return ValidationResult.reject("not_player_turn")
        if stopped:
            return ValidationResult.reject("stopped")
        if flow_state != "PLAYER_TURN":
            return ValidationResult.reject("flow_state")
        key = consumed.key_for(proposed, adapted)
        if consumed.contains(key):
            return ValidationResult.reject("already_consumed")
        return ValidationResult.allow((adapted, key))
