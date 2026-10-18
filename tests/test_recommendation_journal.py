# -*- coding: utf-8 -*-
"""Recommendation journal keeps payloads and execution outcomes on disk."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.recommendation import journal


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self._patches = [
            patch.object(journal, "LOG_DIR", self.dir),
            patch.object(journal, "JOURNAL_PATH", self.dir / "journal.jsonl"),
            patch.object(journal, "LATEST_PATH", self.dir / "latest.json"),
        ]
        for item in self._patches:
            item.start()
        journal._SEEN.clear()
        self.snapshot = SimpleNamespace(
            version=123, turn_number=4,
            payload={"turnNum": 4, "optionId": 7,
                     "data": [{"actionName": "end_turn"}]})

    def tearDown(self):
        for item in reversed(self._patches):
            item.stop()
        journal._SEEN.clear()
        self.tmp.cleanup()

    def test_snapshot_is_written_once_and_latest_is_mirrored(self):
        journal.record_snapshot(self.snapshot)
        journal.record_snapshot(self.snapshot)

        lines = journal.JOURNAL_PATH.read_text(encoding="utf-8").splitlines()
        self.assertEqual(1, len(lines))
        event = json.loads(lines[0])
        self.assertEqual("recommendation", event["event"])
        self.assertEqual(123, event["version"])
        self.assertEqual(4, event["turn"])
        self.assertEqual("end_turn", event["action_name"])
        self.assertEqual(123, json.loads(
            journal.LATEST_PATH.read_text(encoding="utf-8"))["version"])

    def test_execution_outcome_is_appended(self):
        journal.record_execution(
            "battle", 123, "结束回合", "executed", detail="END_TURN")

        event = json.loads(
            journal.JOURNAL_PATH.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual("execution", event["event"])
        self.assertEqual("executed", event["status"])
        self.assertEqual("结束回合", event["instruction"])


if __name__ == "__main__":
    unittest.main()
