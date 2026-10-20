"""告警复核：对触发告警的局部区域做二次检测，抑制单帧误报。"""
from __future__ import annotations

from typing import Any

import cv2
import numpy as np


def crop_with_margin(frame: np.ndarray, bbox: list[int], margin: float = 0.25) -> np.ndarray:
    """按检测框外扩 margin 裁出局部区域，并保证不越界。"""
    h, w = frame.shape[:2]
    x, y, bw, bh = bbox
    mx, my = int(bw * margin), int(bh * margin)
    x1, y1 = max(0, x - mx), max(0, y - my)
    x2, y2 = min(w, x + bw + mx), min(h, y + bh + my)
    return frame[y1:y2, x1:x2]


def prepare_crop(frame: np.ndarray, bbox: list[int], margin: float = 0.25, min_side: int = 96) -> np.ndarray:
    """裁出局部区域；小目标放大后再送检测，避免远景火点被缩没。"""
    crop = crop_with_margin(frame, bbox, margin)
    if crop.size == 0:
        return crop
    h, w = crop.shape[:2]
    scale = min(8.0, max(1.0, min_side / max(1, min(h, w))))
    if scale > 1.0:
        crop = cv2.resize(crop, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_LINEAR)
    return crop


def best_confidence(detections: list[dict[str, Any]], kind: str) -> float:
    return max((d["confidence"] for d in detections if d["type"] == kind), default=0.0)
