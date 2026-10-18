# -*- coding: utf-8 -*-
"""推荐 JSON → ProposedAction 的映射（样本全部来自 2026-10 实机抓包）。"""

import unittest

from src.recommendation.mapper import (
    RecommendationMappingError, payload_to_action)
from src.recommendation_models import ActionKind
from tests.support.recommendation_stubs import payload


class MapperTests(unittest.TestCase):
    def map(self, panel, **kwargs):
        kwargs.setdefault("turn_number", 3)
        kwargs.setdefault("log_revision", 7)
        return payload_to_action(panel, **kwargs)

    # ------------------------------------------------------------ 换牌
    def test_mulligan_slots_come_from_the_card_array(self):
        action = self.map(payload("replace", card=[
            {"cardName": "续连熵能", "cardId": "TIME_026", "ZONE_POSITION": 1},
            {"cardName": "助祭耗材", "cardId": "CATA_499", "ZONE_POSITION": 3},
        ]))

        self.assertEqual(ActionKind.MULLIGAN, action.action)
        self.assertEqual((1, 3), action.mulligan_slots)
        self.assertIn("替换1号位卡牌", action.normalized_instruction)

    def test_keep_all_when_replace_has_no_cards(self):
        action = self.map(payload("replace", card=[]))

        self.assertEqual(ActionKind.MULLIGAN, action.action)
        self.assertEqual((), action.mulligan_slots)
        self.assertEqual("保留全部卡牌", action.normalized_instruction)

    # ------------------------------------------------------------ 出牌
    def test_play_minion_carries_hand_slot_target_and_destination(self):
        # 实机样本：魔眼秘术师 6 号位，目标我方 2 号位，落位 1。
        action = self.map(payload(
            "play_minion",
            card={"ZONE_POSITION": 6, "cardId": "CATA_490",
                  "cardName": "魔眼秘术师"},
            position=1,
            target={"cardId": "BT_300", "cardName": "古尔丹之手",
                    "position": 2},
            using_disguised=0))

        self.assertEqual(ActionKind.PLAY_CARD, action.action)
        self.assertEqual("MINION", action.card_type)
        self.assertEqual(("hand_slot", "friendly", 6),
                         (action.source.kind, action.source.owner,
                          action.source.index))
        self.assertEqual(("board_slot", "friendly", 2),
                         (action.target.kind, action.target.owner,
                          action.target.index))
        self.assertEqual(("board_slot", "friendly", 1),
                         (action.destination.kind, action.destination.owner,
                          action.destination.index))
        self.assertEqual("古尔丹之手", action.target_name)
        self.assertIn("放置于我方1号位", action.normalized_instruction)

    def test_play_special_is_a_spell(self):
        action = self.map(payload(
            "play_special",
            card={"ZONE_POSITION": 2, "cardId": "TLC_451",
                  "cardName": "咒怨之墓"},
            using_disguised=0))

        self.assertEqual("SPELL", action.card_type)
        self.assertEqual(2, action.source.index)
        self.assertIsNone(action.destination)

    # ------------------------------------------------------------ 攻击
    def test_minion_attack_against_enemy_hero(self):
        # 实机样本：oppTargetHero 是一个对象（不是布尔）。
        action = self.map(payload(
            "minion_attack",
            card={"ZONE_POSITION": 1, "cardId": "CATA_490",
                  "cardName": "魔眼秘术师"},
            oppTargetHero={"cardId": "HERO_09a", "cardName": "泰兰德·语风",
                           "health": 30},
            using_disguised=0))

        self.assertEqual(ActionKind.ATTACK, action.action)
        self.assertEqual(1, action.source.index)
        self.assertEqual(("hero", "enemy"),
                         (action.target.kind, action.target.owner))
        self.assertIn("目标是对方英雄", action.normalized_instruction)

    def test_hero_attack_uses_the_hero_as_source(self):
        action = self.map(payload(
            "hero_attack", card={"cardId": "HERO_09a", "cardName": "萨格拉斯"},
            oppTargetHero={"cardId": "HERO_09", "cardName": "泰兰德"}))

        self.assertEqual(("hero", "friendly"),
                         (action.source.kind, action.source.owner))
        self.assertEqual(("hero", "enemy"),
                         (action.target.kind, action.target.owner))

    def test_attack_without_target_is_rejected(self):
        with self.assertRaises(RecommendationMappingError) as ctx:
            self.map(payload("minion_attack", card={"ZONE_POSITION": 1}))

        self.assertEqual("attack_target_required", ctx.exception.code)

    # ------------------------------------------------------------ 技能/地标
    def test_hero_skill(self):
        action = self.map(payload(
            "hero_skill", card={"cardId": "HERO_09a", "cardName": "生命分流"}))
        self.assertEqual(ActionKind.USE_HERO_POWER, action.action)
        self.assertEqual("hero_power", action.source.kind)

    def test_location_power(self):
        action = self.map(payload(
            "location_power",
            card={"ZONE_POSITION": 2, "cardId": "VAC_940",
                  "cardName": "维希度斯的窟穴"}))
        self.assertEqual(ActionKind.USE_LOCATION, action.action)
        self.assertEqual(2, action.source.index)

    # ------------------------------------------------------------ 选择/发现
    def test_choice_uses_target_as_the_chosen_card(self):
        # 实机样本：选择我方3号位卡牌 / 灵魂弹幕。
        action = self.map(payload(
            "choice",
            target={"ZONE_POSITION": 3, "cardId": "RLK_534",
                    "cardName": "灵魂弹幕"}))

        self.assertEqual(ActionKind.CHOOSE_DISCOVER, action.action)
        self.assertEqual(("discover_slot", "friendly", 3),
                         (action.source.kind, action.source.owner,
                          action.source.index))
        self.assertEqual("灵魂弹幕", action.choice_name)
        self.assertNotIn("目标是", action.normalized_instruction)

    # ------------------------------------------------------------ 其它
    def test_end_turn(self):
        action = self.map(payload("end_turn"))
        self.assertEqual(ActionKind.END_TURN, action.action)

    def test_turn_number_comes_from_the_payload(self):
        action = self.map(payload("end_turn", turn=9), turn_number=3)
        self.assertEqual(9, action.turn_number)

    def test_empty_data_is_rejected(self):
        with self.assertRaises(RecommendationMappingError) as ctx:
            self.map({"status": 2, "data": []})
        self.assertEqual("empty_recommendation", ctx.exception.code)

    def test_unsupported_action_is_rejected_with_code(self):
        with self.assertRaises(RecommendationMappingError) as ctx:
            self.map(payload("titan_power", card={"ZONE_POSITION": 1}))
        self.assertEqual("unsupported_action", ctx.exception.code)

    def test_mapping_never_depends_on_ocr(self):
        action = self.map(payload("end_turn"))
        self.assertEqual(1.0, action.ocr_confidence)
        self.assertEqual(1.0, action.semantic_confidence)


if __name__ == "__main__":
    unittest.main()
