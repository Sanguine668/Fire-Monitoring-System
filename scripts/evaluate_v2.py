"""训练后一键评测：官方 test mAP、远景召回、误报率、整图 vs 切片。"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.tiling import merge_detections, tile_frame  # noqa: E402

DATA = ROOT / "datasets" / "fire-smoke-v2-640" / "data.yaml"
LISTS = ROOT / "datasets" / "fire-smoke-v2"


def read_bgr(path: Path):
    with Image.open(path) as im:
        return np.array(im.convert("RGB"))[:, :, ::-1].copy()


def read_list(path: Path) -> list[Path]:
    return [Path(p) for p in path.read_text(encoding="utf-8").splitlines() if p.strip()]


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


def image_level(model, files, conf, expect_positive):
    hit = 0
    for p in files:
        if bool(detect(model, read_bgr(p), conf)) == expect_positive:
            hit += 1
    return hit, len(files)


def tiled_detect(model, frame, conf, tile=640, overlap=0.2):
    merged = []
    for t in tile_frame(frame, tile, overlap):
        for d in detect(model, t.image, conf):
            x, y, w, h = d["bbox"]
            merged.append({**d, "bbox": [x + t.x, y + t.y, w, h]})
    return merge_detections(merged, 0.5)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", default="ai/runs/fire26n-v2/weights/best.pt")
    ap.add_argument("--old", default="ai/runs/fire26n/weights/best.pt")
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--tiling-limit", type=int, default=100)
    args = ap.parse_args()

    new = YOLO(args.weights)
    old = YOLO(args.old) if Path(args.old).is_file() else None
    result: dict = {"weights": args.weights, "conf": args.conf}

    metrics = new.val(
        data=str(DATA), split="test", imgsz=640, device=0,
        batch=8, workers=0, plots=False, verbose=False,
    )
    result["test"] = {
        "mAP50": round(float(metrics.box.map50), 4),
        "mAP50-95": round(float(metrics.box.map), 4),
        "precision": round(float(metrics.box.mp), 4),
        "recall": round(float(metrics.box.mr), 4),
    }

    farfield = read_list(LISTS / "farfield.txt")
    hardneg = read_list(LISTS / "hardneg.txt")
    result["farfield"] = {}
    result["hardneg"] = {}
    for name, model in (("new", new), ("old", old)):
        if model is None:
            continue
        hit, total = image_level(model, farfield, args.conf, True)
        result["farfield"][name] = {"hit": hit, "total": total, "recall": round(hit / total, 4)}
        correct_neg, neg_total = image_level(model, hardneg, args.conf, False)
        fa = neg_total - correct_neg
        result["hardneg"][name] = {"false_alarm": fa, "total": neg_total, "rate": round(fa / neg_total, 4)}
        print(f"[{name}] 远景召回 {hit}/{total}  误报 {fa}/{neg_total}")

    files = farfield[: args.tiling_limit]
    plain_hit = tiled_hit = 0
    plain_t = tiled_t = 0.0
    for p in files:
        img = read_bgr(p)
        t0 = time.perf_counter()
        plain_hit += bool(detect(new, img, args.conf))
        plain_t += time.perf_counter() - t0
        t0 = time.perf_counter()
        tiled_hit += bool(tiled_detect(new, img, args.conf))
        tiled_t += time.perf_counter() - t0
    n = len(files)
    result["tiling"] = {
        "images": n,
        "plain_recall": round(plain_hit / n, 4),
        "tiled_recall": round(tiled_hit / n, 4),
        "plain_ms": round(plain_t / n * 1000, 1),
        "tiled_ms": round(tiled_t / n * 1000, 1),
    }
    out = ROOT / "ai" / "runs" / "eval-v2.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
