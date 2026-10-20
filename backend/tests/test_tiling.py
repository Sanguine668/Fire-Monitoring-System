import numpy as np

from backend.app.tiling import merge_detections, tile_frame


def test_tile_frame_covers_whole_image():
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    tiles = tile_frame(frame, tile_size=640, overlap=0.2)
    assert len(tiles) >= 4
    assert min(t.x for t in tiles) == 0
    assert min(t.y for t in tiles) == 0
    assert max(t.x + t.image.shape[1] for t in tiles) == 1280
    assert max(t.y + t.image.shape[0] for t in tiles) == 720


def test_tile_frame_handles_small_image():
    frame = np.zeros((300, 400, 3), dtype=np.uint8)
    tiles = tile_frame(frame, tile_size=640, overlap=0.2)
    assert len(tiles) == 1
    assert tiles[0].image.shape[:2] == (300, 400)


def test_merge_keeps_highest_confidence_for_same_box():
    dets = [
        {"type": "fire", "confidence": 0.6, "bbox": [10, 10, 50, 50]},
        {"type": "fire", "confidence": 0.9, "bbox": [12, 12, 50, 50]},
        {"type": "smoke", "confidence": 0.7, "bbox": [200, 200, 80, 80]},
    ]
    merged = merge_detections(dets, iou_thr=0.5)
    assert len(merged) == 2
    assert [d for d in merged if d["type"] == "fire"][0]["confidence"] == 0.9


def test_merge_keeps_different_classes_separate():
    dets = [
        {"type": "fire", "confidence": 0.8, "bbox": [0, 0, 50, 50]},
        {"type": "smoke", "confidence": 0.8, "bbox": [5, 5, 50, 50]},
    ]
    assert len(merge_detections(dets, iou_thr=0.5)) == 2
