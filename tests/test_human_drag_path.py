# -*- coding: utf-8 -*-
"""Dragging follows a curved, jittered Bezier path instead of a straight line."""

import math
import random
import unittest
from unittest.mock import patch

import click as hearthstone_click


class _RecordingMouse:
    def __init__(self, position=(0, 0)):
        self._position = position
        self.events = []

    @property
    def position(self):
        return self._position

    @position.setter
    def position(self, value):
        self._position = value
        self.events.append(("position", value))

    def press(self, button):
        self.events.append(("press", button))

    def release(self, button):
        self.events.append(("release", button))


def _max_deviation(points, start, end):
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if not length:
        return 0.0
    return max(abs((x - start[0]) * dy - (y - start[1]) * dx) / length
               for x, y in points)


class BezierTrackTests(unittest.TestCase):
    def test_track_is_curved_and_lands_exactly_on_target(self):
        start, end = (100, 100), (700, 500)

        points = hearthstone_click._bezier_track(
            start, end, rng=random.Random(7))

        self.assertGreater(len(points), 8)
        self.assertEqual(end, points[-1])
        self.assertGreater(_max_deviation(points, start, end), 5.0)
        self.assertTrue(all(a != b for a, b in zip(points, points[1:])))
        self.assertTrue(all(0 <= x <= 800 and 0 <= y <= 600
                            for x, y in points))

    def test_very_short_drag_is_a_single_target_point(self):
        points = hearthstone_click._bezier_track(
            (10, 10), (11, 12), rng=random.Random(2))

        self.assertEqual([(11, 12)], points)


class DragGestureTests(unittest.TestCase):
    def test_drag_presses_then_slides_then_releases(self):
        mouse = _RecordingMouse((100, 100))
        with patch.object(hearthstone_click, "rand_sleep"):
            hearthstone_click._bezier_drag(
                mouse, (100, 100), (500, 400), hold_seconds=0.1)

        positions = [event[1] for event in mouse.events
                     if event[0] == "position"]
        self.assertGreater(len(positions), 2)
        self.assertEqual((100, 100), positions[0])
        self.assertEqual((500, 400), positions[-1])
        self.assertEqual(
            ("press", hearthstone_click.Button.left),
            next(event for event in mouse.events if event[0] == "press"))
        self.assertEqual(
            ("release", hearthstone_click.Button.left), mouse.events[-1])

    def test_release_happens_even_if_slide_fails(self):
        mouse = _RecordingMouse((100, 100))
        with (
            patch.object(hearthstone_click, "rand_sleep"),
            patch.object(hearthstone_click, "_slide_mouse",
                         side_effect=RuntimeError("boom")),
        ):
            with self.assertRaises(RuntimeError):
                hearthstone_click._bezier_drag(
                    mouse, (100, 100), (500, 400))

        self.assertEqual(
            ("release", hearthstone_click.Button.left), mouse.events[-1])

    def test_deck_drag_uses_curve_and_exact_drop_point(self):
        mouse = _RecordingMouse((900, 1000))
        with (
            patch.object(hearthstone_click, "Controller", return_value=mouse),
            patch.object(hearthstone_click, "rand_sleep"),
            patch.object(hearthstone_click, "_display_mapping",
                         return_value=None),
            patch.object(hearthstone_click, "DECK_DROP_HOLD_INTERVAL", 0.2),
        ):
            hearthstone_click.drag_card_to_deck()

        positions = [event[1] for event in mouse.events
                     if event[0] == "position"]
        self.assertGreater(len(positions), 2)
        self.assertEqual((900, 1000), positions[0])
        self.assertEqual((1635, 640), positions[-1])
        self.assertEqual(
            ("release", hearthstone_click.Button.left), mouse.events[-1])


if __name__ == "__main__":
    unittest.main()
