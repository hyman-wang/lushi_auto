"""Validate recommendation evidence immediately before execution."""

from src.recommendation_config import RecommendationConfig
from src.recommendation_models import ValidationResult


def _current_client_size():
    """当前炉石客户区尺寸；拿不到（炉石没开/非 Windows/测试环境）时返回 None。"""
    try:
        import display_mapping
        mapping = display_mapping.display_mapping()
        if mapping is None:
            return None
        return (mapping.width, mapping.height)
    except Exception:
        return None


def _client_size_matches(frame, config) -> bool:
    """这一帧的客户区尺寸是否与当前一致（证据新鲜度）。

    分辨率不再是判定门槛：客户区几何由 display_mapping 换算，任何桌面分辨率
    都能跑。这里只确认"这帧是不是按当前客户区截的"——与**当前**客户区比，
    而不是与 config.desktop_size（基准 1920×1080）比（后者在非 1080p 客户区
    上会永远拒绝）。
    `client_size is None`（旧证据 / 测试构造）时跳过校验。
    """
    client_size = getattr(frame, "client_size", None)
    if client_size is None:
        return True
    try:
        client = tuple(int(v) for v in client_size)
    except Exception:
        return False
    current = _current_client_size()
    if current is not None:
        return client == current
    # 读不到当前几何（离线/测试环境）：退回与基准比较（历史行为）。
    try:
        return client == tuple(int(v) for v in config.desktop_size)
    except Exception:
        return False


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
        self.config = config or RecommendationConfig()

    def validate(self, proposed, adapted, stable_frame, current_frame,
                 current_ocr, state, log_revision,
                 flow_state, consumed, stopped):
        # State/identity freshness must be checked before frame/control gates.
        if proposed.turn_number != state.game_num_turns_in_play:
            return ValidationResult.reject("turn_changed")
        if proposed.log_revision != log_revision:
            return ValidationResult.reject("revision_changed")
        if proposed.ocr_confidence < self.config.min_ocr_confidence:
            return ValidationResult.reject("ocr_confidence")
        if proposed.semantic_confidence < 1.0:
            return ValidationResult.reject("semantic_confidence")
        if not getattr(state, "is_my_turn", False):
            return ValidationResult.reject("not_player_turn")
        if stable_frame.frame_id != proposed.frame_id:
            return ValidationResult.reject("stale_frame")
        if current_ocr.frame_id != current_frame.frame_id:
            return ValidationResult.reject("current_ocr_frame")
        if current_ocr.normalized_text != proposed.normalized_instruction:
            return ValidationResult.reject("recommendation_changed")
        if not _client_size_matches(current_frame, self.config):
            return ValidationResult.reject("desktop_size")
        if current_frame.dpi != self.config.desktop_dpi:
            return ValidationResult.reject("dpi")
        if not current_frame.window_handle or not current_frame.foreground:
            return ValidationResult.reject("window")
        if not current_frame.panel_visible:
            return ValidationResult.reject("recommendation_panel")
        if stopped:
            return ValidationResult.reject("stopped")
        if flow_state != "PLAYER_TURN":
            return ValidationResult.reject("flow_state")
        key = consumed.key_for(proposed, adapted)
        if consumed.contains(key):
            return ValidationResult.reject("already_consumed")
        return ValidationResult.allow((adapted, key))
