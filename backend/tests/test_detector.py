import os

os.environ["FIREGUARD_DEVICE"] = "cpu"

import cv2

from backend.app.config import ROOT
from backend.app.detector import YoloDetector


def test_detector_on_fire_image() -> None:
    image_dir = ROOT / "datasets" / "fire-smoke-voc" / "VOC2020" / "JPEGImages"
    image = next(iter(image_dir.glob("*.jpg")))
    frame = cv2.imread(str(image))
    det = YoloDetector()
    objects = det.detect(frame)
    assert isinstance(objects, list)
    assert all(o["type"] in {"fire", "smoke"} for o in objects)
