import os

os.environ["FIREGUARD_DEVICE"] = "cpu"

import cv2
import numpy as np

from backend.app.config import ROOT
from backend.app.detector import YoloDetector


def test_detector_on_fire_image() -> None:
    det = YoloDetector()
    image_dir = ROOT / "datasets" / "fire-smoke-yolo" / "images" / "val"
    found = []
    for image in sorted(image_dir.glob("*"))[:30]:
        frame = cv2.imdecode(np.fromfile(str(image), dtype=np.uint8), cv2.IMREAD_COLOR)
        assert frame is not None, f"中文路径图片解码失败: {image}"
        found = det.detect(frame)
        if found:
            break
    assert found, "30 张验证图均未检出 fire，请检查模型与类别映射"
    assert all(o["type"] in {"fire", "smoke"} for o in found)
