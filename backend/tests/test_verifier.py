import numpy as np

from backend.app.verifier import best_confidence, crop_with_margin, prepare_crop


def test_crop_clamps_to_image_bounds():
    frame = np.zeros((100, 120, 3), dtype=np.uint8)
    crop = crop_with_margin(frame, [110, 90, 30, 30], margin=0.5)
    assert crop.shape[0] <= 100 and crop.shape[1] <= 120
    assert crop.size > 0


def test_prepare_crop_upscales_small_region():
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    crop = prepare_crop(frame, [100, 100, 20, 16], margin=0.25, min_side=96)
    assert min(crop.shape[:2]) >= 96


def test_best_confidence_filters_by_type():
    dets = [
        {"type": "fire", "confidence": 0.3, "bbox": [0, 0, 1, 1]},
        {"type": "smoke", "confidence": 0.8, "bbox": [0, 0, 1, 1]},
    ]
    assert best_confidence(dets, "fire") == 0.3
    assert best_confidence(dets, "smoke") == 0.8
    assert best_confidence([], "fire") == 0.0
