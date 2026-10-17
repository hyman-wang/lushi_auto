# -*- coding: utf-8 -*-
"""RapidOCR adapter: output mapping, ordering, confidence and failure wrapping."""

import unittest

import numpy as np

from src.ocr.rapid_adapter import OcrUnavailableError, RapidOcrAdapter


class _Output:
    def __init__(self, txts, scores, boxes):
        self.txts = txts
        self.scores = scores
        self.boxes = boxes


class _Engine:
    def __init__(self, output=None, error=None):
        self.output = output
        self.error = error
        self.images = []

    def __call__(self, image):
        self.images.append(image)
        if self.error is not None:
            raise self.error
        return self.output


class RapidOcrAdapterTests(unittest.TestCase):
    def _adapter(self, output=None, error=None):
        engine = _Engine(output=output, error=error)
        captured = {}

        def factory(params):
            captured["params"] = params
            return engine

        adapter = RapidOcrAdapter(engine_factory=factory)
        return adapter, engine, captured

    def test_load_configures_ppocrv6_without_cls_or_score_filtering(self):
        adapter, _engine, captured = self._adapter(_Output((), (), None))

        adapter.load()

        params = captured["params"]
        self.assertFalse(params["Global.use_cls"])
        self.assertEqual(0.0, params["Global.text_score"])
        self.assertIn("EngineConfig.onnxruntime.intra_op_num_threads", params)
        self.assertEqual("rapidocr", adapter.name)

    def test_recognize_maps_boxes_texts_and_scores_in_reading_order(self):
        boxes = np.array([
            [[10, 100], [60, 100], [60, 120], [10, 120]],
            [[10, 10], [60, 10], [60, 30], [10, 30]],
        ])
        adapter, _engine, _captured = self._adapter(
            _Output(("第二行", "第一行"), (0.9, 0.8), boxes))

        evidence = adapter.recognize(
            np.zeros((200, 80, 3), dtype=np.uint8), "frame-1", "scaled_color_v1")

        self.assertEqual("第一行\n第二行", evidence.normalized_text)
        self.assertEqual(["第一行", "第二行"], [line.text for line in evidence.lines])
        self.assertAlmostEqual(0.8, evidence.confidence)
        self.assertEqual("rapidocr", evidence.backend)
        self.assertEqual("scaled_color_v1", evidence.preprocessing)
        self.assertEqual((10.0, 10.0), evidence.lines[0].box[0])

    def test_empty_result_is_reported_as_zero_confidence(self):
        adapter, _engine, _captured = self._adapter(_Output((), (), None))

        evidence = adapter.recognize(
            np.zeros((20, 20, 3), dtype=np.uint8), "frame-2", "gray_clahe_v1")

        self.assertEqual((), evidence.lines)
        self.assertEqual("", evidence.normalized_text)
        self.assertEqual(0.0, evidence.confidence)

    def test_recognition_error_is_wrapped(self):
        adapter, _engine, _captured = self._adapter(error=RuntimeError("boom"))

        with self.assertRaises(OcrUnavailableError) as caught:
            adapter.recognize(
                np.zeros((20, 20, 3), dtype=np.uint8), "frame-3", "candidate")

        self.assertIn("RuntimeError", str(caught.exception))
        self.assertIn("boom", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
