"""推荐源测试替身（CDP 源的无网络版本）。"""

import time

from src.recommendation.cdp_source import RecommendationSnapshot


def payload(action_name="end_turn", *, turn=3, option_id=1, **item):
    """构造一份和盒子推送同形的 payload。"""
    item = {"actionName": action_name, **item}
    return {
        "status": 2,
        "error": "",
        "turnNum": turn,
        "optionId": option_id,
        "choiceId": -1,
        "data": [item],
    }


class FakeSource:
    """可编程推荐源。

    ``bump_after``：第 N 次 snapshot() 之后版本 +1（模拟盒子推了新推荐）；
    ``None`` = 永远同一条（用于验证"不重复点击"）。
    """

    def __init__(self, payload_, version=100, bump_after=None):
        self.payload = payload_
        self.version = version
        self.bump_after = bump_after
        self.calls = 0
        self.last_error = None

    def snapshot(self):
        self.calls += 1
        if self.bump_after is not None and self.calls > self.bump_after:
            self.version += 1
            self.bump_after = None
        return RecommendationSnapshot(self.version, self.payload, time.time())

    def push(self, payload_):
        """模拟盒子主动推一条新推荐。"""
        self.payload = payload_
        self.version += 1
        self.bump_after = None

    def close(self):
        pass
