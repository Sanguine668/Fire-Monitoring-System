"""在指定图片列表上评测模型：按类别统计图级召回与误报。"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image
from ultralytics import YOLO


def read_bgr(path: Path):
    with Image.open(path) as im:
        return np.array(im.convert("RGB"))[:, :, ::-1].copy()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", required=True)
    ap.add_argument("--list", required=True)
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--limit", type=int, default=0, help="0 表示全量")
    ap.add_argument("--negatives", action="store_true", help="列表内全部视为负样本，统计误报率")
    args = ap.parse_args()

    files = [Path(p) for p in Path(args.list).read_text(encoding="utf-8").splitlines() if p.strip()]
    if args.limit:
        files = files[: args.limit]
    model = YOLO(args.weights)
    hit, total = {0: 0, 1: 0}, {0: 0, 1: 0}
    false_alarm = 0
    for f in files:
        if args.negatives:
            want: set[int] = set()
        else:
            label = f.parent.parent / "labels" / (f.stem + ".txt")
            want = {int(ln.split()[0]) for ln in label.read_text().splitlines() if ln.strip()}
            for c in want:
                total[c] += 1
        res = model.predict(read_bgr(f), imgsz=640, conf=args.conf, device=0, verbose=False)[0]
        got = {int(c) for c in res.boxes.cls.tolist()} if res.boxes is not None else set()
        if args.negatives:
            if got:
                false_alarm += 1
            continue
        for c in want & got:
            hit[c] += 1
    for c, name in ((0, "smoke"), (1, "fire")):
        if total[c]:
            print(f"{name}({c}): 图级召回 {hit[c]}/{total[c]} = {hit[c]/total[c]*100:.1f}%  (conf>={args.conf})")
    if args.negatives:
        n = len(files)
        print(f"负样本误报: {false_alarm}/{n} = {false_alarm/n*100:.1f}%  (conf>={args.conf})")
    if not args.negatives and not any(total.values()):
        print("无正样本标注，已跳过召回统计")


if __name__ == "__main__":
    main()
