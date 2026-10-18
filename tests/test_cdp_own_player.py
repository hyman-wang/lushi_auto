# -*- coding: utf-8 -*-
"""Own battle tag is read from the box client-home page, not typed by hand."""

import unittest
from unittest.mock import patch

from src.recommendation.cdp_source import CdpOwnPlayerSource


class OwnPlayerSourceTests(unittest.TestCase):
    def test_btag_is_trimmed(self):
        source = CdpOwnPlayerSource()
        with patch.object(source, "read",
                          return_value={"h": 1, "btag": "  Player#12345  "}):
            self.assertEqual("Player#12345", source.btag())

    def test_missing_btag_returns_none(self):
        source = CdpOwnPlayerSource()
        with patch.object(source, "read", return_value={"h": 1, "btag": ""}):
            self.assertIsNone(source.btag())
        with patch.object(source, "read", return_value=None):
            self.assertIsNone(source.btag())


if __name__ == "__main__":
    unittest.main()
