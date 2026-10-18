"""Immutable evidence and action protocol shared across pipeline layers."""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional


class ActionKind(str, Enum):
    MULLIGAN = "mulligan"
    PLAY_CARD = "play_card"
    TRADE_CARD = "trade_card"
    USE_HERO_POWER = "use_hero_power"
    ATTACK = "attack"
    USE_LOCATION = "use_location"
    LAUNCH_STARSHIP = "launch_starship"
    CHOOSE_DISCOVER = "choose_discover"
    END_TURN = "end_turn"
    TIMELINE_UNDO = "timeline_undo"
    TIMELINE_KEEP = "timeline_keep"


@dataclass(frozen=True)
class SlotRef:
    kind: str
    owner: Optional[str] = None
    index: Optional[int] = None


@dataclass(frozen=True)
class ProposedAction:
    action_id: str
    frame_id: str
    created_at: float
    turn_number: int
    log_revision: int
    raw_instruction: str
    normalized_instruction: str
    action: ActionKind
    source: Optional[SlotRef] = None
    destination: Optional[SlotRef] = None
    target: Optional[SlotRef] = None
    mulligan_slots: tuple[int, ...] = ()
    card_type: Optional[str] = None
    ocr_confidence: float = 0.0
    semantic_confidence: float = 0.0
    choice_name: Optional[str] = None
    # 真实面板在目标行后面还会打印一行「目标卡名」（不带前缀，会被
    # normalize_action_text 过滤掉），单独留一份给「手牌/场面两可」的目标判定用。
    target_name: Optional[str] = None


@dataclass(frozen=True)
class ValidationResult:
    accepted: bool
    code: str
    diagnostics: tuple[str, ...] = ()
    value: Any = None

    @classmethod
    def allow(cls, value: Any) -> "ValidationResult":
        return cls(True, "accepted", value=value)

    @classmethod
    def reject(cls, code: str, *diagnostics: str) -> "ValidationResult":
        return cls(False, code, diagnostics)
