"""同一模型、同一小目标子集上，对比整图推理与切片推理的图级召回与耗时。"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
from PIL import Image
from ultralytics import YOLO

from backend.app.tiling import merge_detections, tile_frame


def read_bgr(path: Path):
    with Image.open(path) as im:
        return np.array(im.convert("RGB"))[:, :, ::-1].copy()


def detect(model, frame, conf):
    res = model.predict(frame, imgsz=640, conf=conf, device=0, verbose=False)[0]
    if res.boxes is None:
        return []
    out = []
    for box, c, ci in zip(res.boxes.xyxy.cpu().numpy(), res.boxes.conf.cpu().numpy(),
                          res.boxes.cls.cpu().numpy()):
        x1, y1, x2, y2 = map(float, box)
        out.append({
            "type": "fire" if int(ci) == 1 else "smoke",
            "confidence": float(c),
            "bbox": [round(x1), round(y1), round(x2 - x1), round(y2 - y1)],
        })
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", required=True)
    ap.add_argument("--list", default="datasets/fire-smoke-v2/farfield.txt")
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--limit", type=int, default=200)
    args = ap.parse_args()

    files = [Path(p) for p in Path(args.list).read_text(encoding="utf-8").splitlines() if p.strip()]
    files = files[: args.limit]
    model = YOLO(args.weights)
    plain_hit = tiled_hit = 0
    plain_t = tiled_t = 0.0
    for i, f in enumerate(files, 1):
        img = read_bgr(f)
        t0 = time.perf_counter()
        if detect(model, img, args.conf):
            plain_hit += 1
        plain_t += time.perf_counter() - t0

        t0 = time.perf_counter()
        merged = []
        for tile in tile_frame(img, 640, 0.2):
            for d in detect(model, tile.image, args.conf):
                x, y, w, h = d["bbox"]
                merged.append({**d, "bbox": [x + tile.x, y + tile.y, w, h]})
        if merge_detections(merged, 0.5):
            tiled_hit += 1
        tiled_t += time.perf_counter() - t0
        if i % 20 == 0:
            print(f"  已处理 {i}/{len(files)}")

    n = len(files)
    print(f"整图推理: 图级召回 {plain_hit}/{n} = {plain_hit/n*100:.1f}%   平均 {plain_t/n*1000:.0f} ms/帧")
    print(f"切片推理: 图级召回 {tiled_hit}/{n} = {tiled_hit/n*100:.1f}%   平均 {tiled_t/n*1000:.0f} ms/帧")
    print(f"召回提升: {(tiled_hit - plain_hit)/n*100:+.1f} 个百分点")


if __name__ == "__main__":
    main()
