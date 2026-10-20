"""切片推理：把大图切成瓦片分别检测，再把结果合并回全图。"""
from __future__ import annotations

from collections import namedtuple
from typing import Any

import numpy as np

Tile = namedtuple("Tile", "x y image")


def _axis_starts(length: int, tile: int, step: int) -> list[int]:
    if length <= tile:
        return [0]
    starts = list(range(0, length - tile + 1, step))
    if starts[-1] != length - tile:  # 保证最后一片贴住边界
        starts.append(length - tile)
    return sorted(set(starts))


def tile_frame(frame: np.ndarray, tile_size: int = 640, overlap: float = 0.2) -> list[Tile]:
    """按固定步长切图，保证四条边都被覆盖；小图直接返回整图。"""
    h, w = frame.shape[:2]
    step = max(1, int(tile_size * (1 - overlap)))
    tiles: list[Tile] = []
    for y in _axis_starts(h, tile_size, step):
        for x in _axis_starts(w, tile_size, step):
            tiles.append(Tile(x, y, frame[y:y + tile_size, x:x + tile_size]))
    return tiles


def _iou(a: list[int], b: list[int]) -> float:
    ax1, ay1, aw, ah = a
    bx1, by1, bw, bh = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax1 + aw, bx1 + bw), min(ay1 + ah, by1 + bh)
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    if inter <= 0:
        return 0.0
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def merge_detections(items: list[dict[str, Any]], iou_thr: float = 0.5) -> list[dict[str, Any]]:
    """同一类别内按置信度降序做 NMS；不同类别互不抑制。"""
    kept: list[dict[str, Any]] = []
    for item in sorted(items, key=lambda d: d["confidence"], reverse=True):
        if any(k["type"] == item["type"] and _iou(k["bbox"], item["bbox"]) >= iou_thr for k in kept):
            continue
        kept.append(item)
    return kept
