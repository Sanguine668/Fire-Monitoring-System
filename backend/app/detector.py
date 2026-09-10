from __future__ import annotations

import os
import threading
from typing import Any

import cv2

from .config import MODEL_PATH


class YoloDetector:
    def __init__(self, model_path: str | None = None) -> None:
        from ultralytics import YOLO

        path = str(model_path or MODEL_PATH)
        self.model = YOLO(path)
        self._lock = threading.RLock()
        self.names = {v: str(k).lower() for k, v in self.model.names.items()}

    def detect(self, frame) -> list[dict[str, Any]]:
        import torch

        device: Any = os.environ.get("FIREGUARD_DEVICE")
        if device is None:
            device = 0 if torch.cuda.is_available() else "cpu"
        with self._lock:
            results = self.model.predict(frame, imgsz=640, conf=0.1, device=device, verbose=False)
        out: list[dict[str, Any]] = []
        for r in results:
            if r.boxes is None:
                continue
            xyxy = r.boxes.xyxy.cpu().numpy()
            confs = r.boxes.conf.cpu().numpy()
            cls = r.boxes.cls.cpu().numpy().astype(int)
            for box, c, ci in zip(xyxy, confs, cls):
                name = self.names.get(int(ci), "unknown")
                if name not in {"fire", "smoke"}:
                    continue
                x1, y1, x2, y2 = map(float, box)
                out.append(
                    {
                        "type": name,
                        "confidence": float(c),
                        "bbox": [round(x1), round(y1), round(x2 - x1), round(y2 - y1)],
                    }
                )
        return out


def draw_detections(frame, detections: list[dict[str, Any]]) -> None:
    for d in detections:
        x, y, w, h = d["bbox"]
        color = (0, 0, 255) if d["type"] == "fire" else (0, 165, 255)
        cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
        label = f"{d['type']} {d['confidence']:.2f}"
        cv2.putText(frame, label, (x, max(0, y - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
