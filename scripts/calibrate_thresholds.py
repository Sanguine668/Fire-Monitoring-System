"""用验证集正样本与困难负样本，扫描 fire/smoke 阈值，给出召回-误报曲线。"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[1]
LISTS = ROOT / "datasets" / "fire-smoke-v2"


def read_bgr(path: Path):
    with Image.open(path) as im:
        return np.array(im.convert("RGB"))[:, :, ::-1].copy()


def read_list(path: Path) -> list[Path]:
    return [Path(p) for p in path.read_text(encoding="utf-8").splitlines() if p.strip()]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", default="ai/runs/fire26n-v2/weights/best.pt")
    ap.add_argument("--positives", type=int, default=600)
    ap.add_argument("--negatives", type=int, default=800)
    args = ap.parse_args()

    model = YOLO(args.weights)
    val = read_list(LISTS / "val.txt")
    fire_files, smoke_files = [], []
    for p in val:
        label = p.parent.parent / "labels" / (p.stem + ".txt")
        classes = {int(ln.split()[0]) for ln in label.read_text().splitlines() if ln.strip()}
        if 1 in classes:
            fire_files.append(p)
        if 0 in classes:
            smoke_files.append(p)
    fire_files = fire_files[: args.positives]
    smoke_files = smoke_files[: args.positives]
    neg_files = read_list(LISTS / "hardneg.txt")[: args.negatives]

    def max_conf(files, want):
        values = []
        for p in files:
            res = model.predict(read_bgr(p), imgsz=640, conf=0.05, device=0, verbose=False)[0]
            best = 0.0
            if res.boxes is not None and len(res.boxes):
                names = res.names
                for c, ci in zip(res.boxes.conf.cpu().numpy(), res.boxes.cls.cpu().numpy()):
                    if str(names[int(ci)]).lower() == want:
                        best = max(best, float(c))
            values.append(best)
        return np.array(values)

    fire_pos = max_conf(fire_files, "fire")
    smoke_pos = max_conf(smoke_files, "smoke")
    fire_neg = max_conf(neg_files, "fire")
    smoke_neg = max_conf(neg_files, "smoke")

    print(f"正样本: fire {len(fire_pos)}  smoke {len(smoke_pos)}  负样本 {len(fire_neg)}")
    print("thr   fire召回  fire误报  smoke召回  smoke误报")
    for t in np.arange(0.05, 0.95, 0.05):
        print(
            f"{t:.2f}  {np.mean(fire_pos >= t)*100:7.1f}%  {np.mean(fire_neg >= t)*100:8.1f}%"
            f"  {np.mean(smoke_pos >= t)*100:8.1f}%  {np.mean(smoke_neg >= t)*100:9.1f}%"
        )


if __name__ == "__main__":
    main()
