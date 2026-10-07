"""Deterministic computer-vision layer.

Always on (Pillow + NumPy only): resolution, brightness, contrast, sharpness, dominant palette, colour
temperature and capture-quality flags. These are *measured* facts, reported separately from the LLM's
interpretation.

Optional: object detection through a pluggable ``ObjectDetector``. ``UltralyticsDetector`` activates when the
``ultralytics`` package is installed and CV_DETECTOR_MODEL points at weights; otherwise ``NullDetector``
returns no detections and says so. We never fabricate detections.
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass, field
from typing import Any, Protocol, cast

import numpy as np
from PIL import Image


@dataclass
class Detection:
    label: str
    confidence: float
    box: tuple[float, float, float, float]  # x1, y1, x2, y2 normalised 0..1


class ObjectDetector(Protocol):
    name: str

    def detect(self, image: Image.Image) -> list[Detection]: ...


class NullDetector:
    name = "none"

    def detect(self, image: Image.Image) -> list[Detection]:
        return []


class UltralyticsDetector:
    """YOLO-family detector. Generic COCO weights recognise common furniture (chair, couch, bed, tv, sink...)."""

    def __init__(self, weights: str, min_conf: float = 0.35):
        from ultralytics import YOLO  # optional dependency (requirements-ml.txt)

        self._model = YOLO(weights)
        self._min_conf = min_conf
        self.name = f"ultralytics:{os.path.basename(weights)}"

    def detect(self, image: Image.Image) -> list[Detection]:
        res = self._model.predict(image, conf=self._min_conf, verbose=False)[0]
        w, h = image.size
        out = []
        for b in res.boxes:
            x1, y1, x2, y2 = (float(v) for v in b.xyxy[0].tolist())
            out.append(Detection(res.names[int(b.cls[0])], round(float(b.conf[0]), 3), (x1 / w, y1 / h, x2 / w, y2 / h)))
        return out


def build_detector(weights: str | None) -> ObjectDetector:
    if not weights:
        return NullDetector()
    try:
        return UltralyticsDetector(weights)
    except Exception:  # missing package / weights: degrade honestly
        return NullDetector()


@dataclass
class CVResult:
    width: int
    height: int
    brightness: float
    contrast: float
    sharpness: float
    palette: list[dict[str, Any]]
    color_temperature: str
    quality_flags: list[str]
    detector: str = "none"
    detections: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _laplacian_variance(gray: np.ndarray) -> float:
    a = gray.astype(np.float32)
    lap = -4 * a[1:-1, 1:-1] + a[:-2, 1:-1] + a[2:, 1:-1] + a[1:-1, :-2] + a[1:-1, 2:]
    return float(lap.var())


def analyze_image_bytes(data: bytes, detector: ObjectDetector | None = None) -> CVResult:
    detector = detector or NullDetector()
    with Image.open(io.BytesIO(data)) as im:
        rgb = im.convert("RGB")
        width, height = rgb.size
        small = rgb.copy()
        small.thumbnail((512, 512))
        arr = np.asarray(small)
        gray = np.asarray(small.convert("L"))
        brightness = float(gray.mean())
        contrast = float(gray.std())
        sharpness = _laplacian_variance(gray)

        q = small.quantize(colors=5, method=Image.Quantize.MEDIANCUT)
        pal = q.getpalette() or []
        total = small.width * small.height
        palette = []
        for count, idx in sorted(cast(list[tuple[int, int]], q.getcolors() or []), reverse=True):
            r, g, b = pal[idx * 3: idx * 3 + 3]
            palette.append({"hex": f"#{r:02x}{g:02x}{b:02x}", "share": round(count / total, 3)})

        r_mean, b_mean = float(arr[..., 0].mean()), float(arr[..., 2].mean())
        diff = r_mean - b_mean
        temp = "warm" if diff > 12 else "cool" if diff < -12 else "neutral"

        flags = []
        if brightness < 60:
            flags.append("too_dark")
        elif brightness > 210:
            flags.append("overexposed")
        if sharpness < 40:
            flags.append("possibly_blurry")
        if min(width, height) < 640:
            flags.append("low_resolution")
        if contrast < 25:
            flags.append("low_contrast")

        dets = [{"label": d.label, "confidence": d.confidence, "box": d.box} for d in detector.detect(rgb)]
    return CVResult(width, height, round(brightness, 1), round(contrast, 1), round(sharpness, 1), palette, temp, flags,
                    detector.name, dets)
