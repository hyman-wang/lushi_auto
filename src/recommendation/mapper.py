"""把盒子推送的推荐 JSON 映射成内部的 ProposedAction。

字段来自 2026-10 实测（见 docs/cdp-recommendation.md）：

    {
      "status": 2, "error": "", "turnNum": 3, "optionId": 11, "choiceId": -1,
      "data": [
        {"actionName": "play_minion",
         "card": {"ZONE_POSITION": 6, "cardId": "CATA_490", "cardName": "魔眼秘术师"},
         "position": 1,
         "target": {"cardId": "BT_300", "cardName": "古尔丹之手", "position": 2},
         "using_disguised": 0}
      ]
    }

约定：
  * ``data[0]`` = 打法参考A，``data[1]`` = 打法参考B（B 目前只用于日志）。
  * ``card.ZONE_POSITION`` 是手牌/场面号位；``position`` 是落位。
  * ``target`` 是己方目标，``oppTarget`` 是对方目标；
    ``targetHero`` / ``oppTargetHero`` 是英雄（实测为对象，含 cardId/health）。
"""

from __future__ import annotations

import json
import time
from typing import Any, Optional

from src.recommendation_models import ActionKind, ProposedAction, SlotRef


class RecommendationMappingError(ValueError):
    """推荐 JSON 无法映射（动作不支持 / 字段缺失）。"""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code


_CARD_TYPES = {
    "play_minion": "MINION",
    "play_special": "SPELL",
    "play_weapon": "WEAPON",
    "play_hero": "HERO",
    "play_location": "LOCATION",
}

_ACTION_LABELS = {
    "end_turn": "结束回合",
    "play_minion": "打出{pos}号位随从",
    "play_special": "打出{pos}号位法术",
    "play_weapon": "打出{pos}号位武器",
    "play_hero": "打出{pos}号位英雄",
    "play_location": "打出{pos}号位地标",
    "forge": "锻造{pos}号位卡牌",
    "trade": "交易{pos}号位卡牌",
    "prepare": "预备{pos}号位卡牌",
    "hero_attack": "操作我方英雄攻击",
    "minion_attack": "操作{pos}号位随从攻击",
    "hero_skill": "使用英雄技能",
    "titan_power": "操作{pos}号位泰坦",
    "location_power": "操作{pos}号位地标",
    "launch_starship": "发射{pos}号位星舰",
    "common_action": "操作{pos}号位卡牌",
    "choice": "选择我方{pos}号位卡牌",
    "replace": "替换{pos}号位卡牌",
}


def _position(obj: Any) -> Optional[int]:
    """卡牌/目标上的号位：实测 position 与 ZONE_POSITION 两种键都出现过。"""
    if not isinstance(obj, dict):
        return None
    for key in ("ZONE_POSITION", "position"):
        value = obj.get(key)
        try:
            if value is not None:
                return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _cards(item: dict) -> list:
    card = item.get("card")
    if isinstance(card, list):
        return [c for c in card if isinstance(c, dict)]
    if isinstance(card, dict):
        return [card]
    return []


def _first_card(item: dict) -> dict:
    cards = _cards(item)
    return cards[0] if cards else {}


def _hero_target(item: dict) -> Optional[SlotRef]:
    if item.get("oppTargetHero"):
        return SlotRef("hero", "enemy")
    if item.get("targetHero"):
        return SlotRef("hero", "friendly")
    return None


def _board_target(item: dict) -> Optional[SlotRef]:
    for key, owner in (("oppTarget", "enemy"), ("target", "friendly")):
        obj = item.get(key)
        position = _position(obj)
        if position is not None:
            return SlotRef("board_slot", owner, position)
    return None


def _target(item: dict) -> Optional[SlotRef]:
    return _hero_target(item) or _board_target(item)


def _target_name(item: dict) -> Optional[str]:
    for key in ("target", "oppTarget"):
        obj = item.get(key)
        if isinstance(obj, dict) and obj.get("cardName"):
            return str(obj["cardName"])
    for key in ("targetHero", "oppTargetHero"):
        obj = item.get(key)
        if isinstance(obj, dict) and obj.get("cardName"):
            return str(obj["cardName"])
    return None


def _render_lines(item: dict, cards: list) -> list:
    """按面板文案还原成人能读的几行（只用于日志，不参与点击定位）。"""
    name = item.get("actionName")
    card = cards[0] if cards else {}
    position = _position(card)
    if name == "replace":
        if not cards:
            return ["保留全部卡牌"]
        return ["替换%d号位卡牌" % _position(c) for c in cards
                if _position(c) is not None]
    if name == "choice":
        # 面板：「选择我方3号位卡牌 / 灵魂弹幕」——target 是待选的那张牌，不是目标。
        chosen = item.get("target") if isinstance(item.get("target"), dict) else {}
        lines = ["选择我方%s号位卡牌" % (_position(chosen) or "")]
        if chosen.get("cardName"):
            lines.append(str(chosen["cardName"]))
        opp = item.get("oppTarget")
        if isinstance(opp, dict) and _position(opp) is not None:
            lines.append("目标是对方%d号位" % _position(opp))
        return lines
    label = _ACTION_LABELS.get(name)
    if label is None:
        return [str(name)]
    lines = [label.format(pos=position if position is not None else "")]
    if card.get("cardName"):
        lines.append(str(card["cardName"]))
    target = _target(item)
    if target is not None:
        if target.kind == "hero":
            lines.append("目标是%s英雄" % ("对方" if target.owner == "enemy" else "我方"))
        else:
            lines.append("目标是%s%d号位" % (
                "对方" if target.owner == "enemy" else "我方", target.index))
        target_name = _target_name(item)
        if target_name:
            lines.append(target_name)
    if name == "play_minion" and item.get("position") is not None:
        lines.append("放置于%s%s号位" % (
            "对手" if item.get("using_disguised") == 1 else "我方",
            item.get("position")))
    sub = item.get("subOption")
    if isinstance(sub, dict) and (sub.get("cardName") or sub.get("cardId")):
        lines.append("选择卡牌")
        lines.append(str(sub.get("cardName") or sub.get("cardId")))
    return lines


def _build(item: dict, *, action: ActionKind, source=None, destination=None,
           target=None, card_type=None, mulligan_slots=(), choice_name=None,
           target_name=None) -> dict:
    """收集映射结果；``item`` 只为保留调用处的上下文，不参与组装。"""
    del item
    return {
        "action": action,
        "source": source,
        "destination": destination,
        "target": target,
        "card_type": card_type,
        "mulligan_slots": mulligan_slots,
        "choice_name": choice_name,
        "target_name": target_name,
    }


def _map_item(item: dict) -> dict:
    name = item.get("actionName")
    if not isinstance(name, str) or not name:
        raise RecommendationMappingError("missing_action_name")

    cards = _cards(item)
    card = cards[0] if cards else {}
    hand_slot = _position(card)
    target = _target(item)

    if name == "end_turn":
        return _build(item, action=ActionKind.END_TURN)

    if name == "replace":
        slots = tuple(sorted({p for p in (_position(c) for c in cards)
                              if p is not None}))
        return _build(item, action=ActionKind.MULLIGAN, mulligan_slots=slots)

    if name in _CARD_TYPES:
        if hand_slot is None:
            raise RecommendationMappingError("missing_hand_slot", name)
        destination = None
        if name == "play_minion" and item.get("position") is not None:
            try:
                destination = SlotRef(
                    "board_slot", "friendly", int(item["position"]))
            except (TypeError, ValueError):
                destination = None
        card_type = _CARD_TYPES[name]
        return _build(
            item, action=ActionKind.PLAY_CARD,
            source=SlotRef("hand_slot", "friendly", hand_slot),
            destination=destination, target=target, card_type=card_type,
            target_name=_target_name(item) if card_type == "MINION" else None)

    if name in ("trade", "forge", "prepare"):
        if hand_slot is None:
            raise RecommendationMappingError("missing_hand_slot", name)
        return _build(item, action=ActionKind.TRADE_CARD,
                      source=SlotRef("hand_slot", "friendly", hand_slot))

    if name == "minion_attack":
        if hand_slot is None:
            raise RecommendationMappingError("missing_board_slot", name)
        if target is None:
            raise RecommendationMappingError("attack_target_required")
        return _build(item, action=ActionKind.ATTACK,
                      source=SlotRef("board_slot", "friendly", hand_slot),
                      target=target)

    if name == "hero_attack":
        if target is None:
            raise RecommendationMappingError("attack_target_required")
        return _build(item, action=ActionKind.ATTACK,
                      source=SlotRef("hero", "friendly"), target=target)

    if name == "hero_skill":
        return _build(item, action=ActionKind.USE_HERO_POWER,
                      source=SlotRef("hero_power", "friendly"), target=target)

    if name == "location_power":
        if hand_slot is None:
            raise RecommendationMappingError("missing_board_slot", name)
        return _build(item, action=ActionKind.USE_LOCATION,
                      source=SlotRef("board_slot", "friendly", hand_slot),
                      target=target)

    if name == "launch_starship":
        if hand_slot is None:
            raise RecommendationMappingError("missing_board_slot", name)
        return _build(item, action=ActionKind.LAUNCH_STARSHIP,
                      source=SlotRef("board_slot", "friendly", hand_slot))

    if name == "choice":
        # 「选择我方3号位卡牌」：target 是待选的那张牌，号位在 target.ZONE_POSITION。
        chosen = item.get("target") if isinstance(item.get("target"), dict) else {}
        slot = _position(chosen)
        if slot is None:
            raise RecommendationMappingError("missing_choice_slot", name)
        return _build(
            item, action=ActionKind.CHOOSE_DISCOVER,
            source=SlotRef("discover_slot", "friendly", slot),
            # 发现/选项如果还要再点一个目标，走 oppTarget / hero 标记
            target=_hero_target(item) or (
                SlotRef("board_slot", "enemy", _position(item["oppTarget"]))
                if isinstance(item.get("oppTarget"), dict)
                and _position(item["oppTarget"]) is not None else None),
            choice_name=chosen.get("cardName"))

    if name == "timeline_undo":
        return _build(item, action=ActionKind.TIMELINE_UNDO)
    if name == "timeline_keep":
        return _build(item, action=ActionKind.TIMELINE_KEEP)

    raise RecommendationMappingError("unsupported_action", str(name))


def payload_to_action(payload: dict, *, turn_number: int, log_revision: int,
                      frame_id: str = "") -> ProposedAction:
    """把一份推荐 payload 转成 ``ProposedAction``（默认取打法参考A）。"""
    if not isinstance(payload, dict):
        raise RecommendationMappingError("invalid_payload")
    actions = payload.get("data")
    if not isinstance(actions, list) or not actions:
        raise RecommendationMappingError("empty_recommendation")
    items = [item for item in actions if isinstance(item, dict)]
    if not items:
        raise RecommendationMappingError("empty_recommendation")

    item = items[0]
    mapped = _map_item(item)
    lines = _render_lines(item, _cards(item))
    normalized = "\n".join(line for line in lines if line)
    try:
        payload_turn = int(payload.get("turnNum"))
    except (TypeError, ValueError):
        payload_turn = int(turn_number)

    return ProposedAction(
        action_id="cdp-%s" % payload.get("optionId", "na"),
        frame_id=frame_id or "cdp",
        created_at=time.time(),
        turn_number=payload_turn,
        log_revision=int(log_revision),
        raw_instruction=json.dumps(payload, ensure_ascii=False),
        normalized_instruction=normalized,
        action=mapped["action"],
        source=mapped["source"],
        destination=mapped["destination"],
        target=mapped["target"],
        mulligan_slots=mapped["mulligan_slots"],
        card_type=mapped["card_type"],
        # 不再有 OCR：置信度固定 1.0（数值来源是盒子的结构化推送）。
        ocr_confidence=1.0,
        semantic_confidence=1.0,
        choice_name=mapped["choice_name"],
        target_name=mapped["target_name"],
    )
