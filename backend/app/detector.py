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
        raw_names = self.model.names
        if isinstance(raw_names, dict) and all(isinstance(k, str) for k in raw_names):
            id2name = {int(v): k for k, v in raw_names.items()}
        elif isinstance(raw_names, dict):
            id2name = raw_names
        else:
            id2name = dict(enumerate(raw_names))
        self.id2name = {int(k): str(v).lower() for k, v in id2name.items()}

    def _predict(self, frames, conf: float) -> list[list[dict[str, Any]]]:
        import torch

        device: Any = os.environ.get("FIREGUARD_DEVICE")
        if device is None:
            device = 0 if torch.cuda.is_available() else "cpu"
        with self._lock:
            results = self.model.predict(frames, imgsz=640, conf=conf, device=device, verbose=False)
        out: list[list[dict[str, Any]]] = []
        for r in results:
            dets: list[dict[str, Any]] = []
            if r.boxes is None:
                out.append(dets)
                continue
            xyxy = r.boxes.xyxy.cpu().numpy()
            confs = r.boxes.conf.cpu().numpy()
            cls = r.boxes.cls.cpu().numpy().astype(int)
            for box, c, ci in zip(xyxy, confs, cls):
                name = self.id2name.get(int(ci), "unknown")
                if name not in {"fire", "smoke"}:
                    continue
                x1, y1, x2, y2 = map(float, box)
                dets.append(
                    {
                        "type": name,
                        "confidence": float(c),
                        "bbox": [round(x1), round(y1), round(x2 - x1), round(y2 - y1)],
                    }
                )
            out.append(dets)
        return out

    def detect(self, frame, conf: float = 0.05) -> list[dict[str, Any]]:
        return self._predict([frame], conf)[0]

    def detect_tiled(
        self,
        frame,
        tile_size: int = 640,
        overlap: float = 0.2,
        iou_thr: float = 0.5,
        conf: float = 0.05,
    ) -> list[dict[str, Any]]:
        """切片推理：逐片检测后把坐标平移回全图并合并。"""
        from .tiling import merge_detections, tile_frame

        tiles = tile_frame(frame, tile_size, overlap)
        merged: list[dict[str, Any]] = []
        for tile, dets in zip(tiles, self._predict([t.image for t in tiles], conf)):
            for det in dets:
                x, y, w, h = det["bbox"]
                merged.append({
                    "type": det["type"],
                    "confidence": det["confidence"],
                    "bbox": [x + tile.x, y + tile.y, w, h],
                })
        return merge_detections(merged, iou_thr)

    def verify_region(
        self,
        frame,
        bbox: list[int],
        expected_type: str,
        min_conf: float = 0.2,
        margin: float = 0.25,
    ) -> tuple[bool, float]:
        """对告警区域做二次检测；返回（是否通过复核，同类最高置信度）。"""
        from .verifier import best_confidence, prepare_crop

        crop = prepare_crop(frame, bbox, margin)
        if crop.size == 0:
            return False, 0.0
        conf = best_confidence(self.detect(crop, conf=min_conf), expected_type)
        return conf >= min_conf, conf


def draw_detections(frame, detections: list[dict[str, Any]]) -> None:
    for d in detections:
        x, y, w, h = d["bbox"]
        color = (0, 0, 255) if d["type"] == "fire" else (0, 165, 255)
        cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
        label = f"{d['type']} {d['confidence']:.2f}"
        cv2.putText(frame, label, (x, max(0, y - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
