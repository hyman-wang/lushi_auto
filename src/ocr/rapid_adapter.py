"""RapidOCR (PP-OCRv6 small, ONNX Runtime) boundary with normalized evidence output."""

import os
import time
from pathlib import Path

import cv2

from src.recommendation_config import RecommendationConfig
from src.recommendation_models import OcrEvidence, OcrLine


class OcrUnavailableError(RuntimeError):
    pass


def _recommended_threads() -> int:
    """按机器实际情况推荐 ONNX Runtime 的 intra-op 线程数。

    优先取物理核数；超线程对这类小模型推理收益有限，还会和游戏/盒子抢核。
    无法取到时按逻辑核折半。下限取配置 ocr_thread_min（默认 4）。
    """
    minimum = RecommendationConfig().ocr_thread_min
    try:
        import psutil
        physical = psutil.cpu_count(logical=False)
        if physical:
            return max(minimum, int(physical))
    except Exception:
        pass
    logical = os.cpu_count() or minimum
    return max(minimum, logical // 2)


class RapidOcrAdapter:
    name = "rapidocr"

    def __init__(self, engine=None, clock=time.time, engine_factory=None):
        self.engine = engine
        self.clock = clock
        self.engine_factory = engine_factory
        # 每次 OCR 的输入图按顺序存盘（会话子目录，便于调试查看到底
        # 识别了多大的图）。优先级：
        #   1. 环境变量 OCR_FRAME_DIR
        #   2. config.ocr_frame_dump_dir（可清空关闭）
        frame_root = os.environ.get(
            "OCR_FRAME_DIR", RecommendationConfig().ocr_frame_dump_dir)
        self._frame_counter = 0
        self._frame_dir = None
        if frame_root and frame_root != "0":
            run_dir = Path(frame_root) / time.strftime("run_%H%M%S")
            run_dir.mkdir(parents=True, exist_ok=True)
            self._frame_dir = run_dir
            print(f"[OCR] 本会话自动保存截图: {run_dir}")

    def load(self):
        if self.engine is not None:
            return self
        try:
            threads = str(_recommended_threads())
            # ONNX Runtime / OpenMP 的线程数：setdefault 保留用户显式覆盖。
            os.environ.setdefault("OMP_NUM_THREADS", threads)
            os.environ.setdefault("MKL_NUM_THREADS", threads)
            print(f"[OCR] 推理线程 ORT={threads}")
            if self.engine_factory is None:
                from rapidocr import RapidOCR
                self.engine_factory = RapidOCR
            self.engine = self.engine_factory(params={
                # 界面是正向文字，不需要 180° 方向分类。
                "Global.use_cls": False,
                # 不要在引擎内部按分数丢行：置信度由 StableRecommendationReader
                # 统一判定，丢行会让“最低置信度”虚高，把不稳定文本误判为稳定。
                "Global.text_score": 0.0,
                "Global.log_level": "warning",
                "EngineConfig.onnxruntime.intra_op_num_threads": int(threads),
                "EngineConfig.onnxruntime.inter_op_num_threads": 1,
            })
        except Exception as exc:
            raise OcrUnavailableError(
                f"RapidOCR unavailable: {type(exc).__name__}: {exc}") from exc
        return self

    def recognize(self, image, frame_id, preprocessing):
        self.load()
        started = time.perf_counter()
        try:
            raw = self.engine(image)
        except Exception as exc:
            raise OcrUnavailableError(
                f"RapidOCR recognition failed: {type(exc).__name__}: {exc}") from exc
        lines = []
        if raw is not None and getattr(raw, "txts", None):
            boxes = getattr(raw, "boxes", None)
            scores = getattr(raw, "scores", None)
            for index, text in enumerate(raw.txts):
                text = str(text).strip()
                if not text:
                    continue
                confidence = (float(scores[index])
                              if scores is not None and index < len(scores)
                              else 0.0)
                box = boxes[index] if boxes is not None and index < len(boxes) else ()
                lines.append(OcrLine(
                    text, confidence,
                    tuple((float(x), float(y)) for x, y in box)))
        lines.sort(key=lambda item: min(
            (point[1] for point in item.box), default=0.0))
        normalized = "\n".join(line.text for line in lines if line.text)
        confidence = min((line.confidence for line in lines), default=0.0)
        height, width = image.shape[:2] if image is not None else (0, 0)
        print(f"[OCR] 图 {width}x{height} 行 {len(lines)} 置信 {confidence:.2f} "
              f"耗时 {(time.perf_counter() - started) * 1000:.0f}ms "
              f"({preprocessing})")
        if self._frame_dir is not None:
            self._frame_counter += 1
            safe_name = str(preprocessing or "frame").replace("/", "_")
            cv2.imwrite(
                str(self._frame_dir / f"{self._frame_counter:03d}_{safe_name}.png"),
                image)
        return OcrEvidence(
            frame_id, self.clock(), tuple(lines), normalized, confidence,
            self.name, preprocessing)
