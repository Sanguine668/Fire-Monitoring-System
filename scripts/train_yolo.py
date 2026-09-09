from __future__ import annotations

import argparse
from pathlib import Path

from ultralytics import YOLO


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="yolo26n.pt", help="预训练权重名或路径")
    parser.add_argument("--name", default="fire26n")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--workers", type=int, default=0, help="Windows 环境建议 0，避免多进程加载 torch 触发 WinError 1455")
    args = parser.parse_args()

    data_yaml = root / "datasets" / "fire-smoke-yolo" / "data.yaml"
    if not data_yaml.is_file():
        raise SystemExit(f"缺少 data.yaml: {data_yaml}")

    model = YOLO(args.model)
    model.train(
        data=str(data_yaml),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=0,
        patience=20,
        seed=42,
        amp=True,
        project=str(root / "ai" / "runs"),
        name=args.name,
        exist_ok=True,
        workers=args.workers,
    )
    metrics = model.val(data=str(data_yaml), split="val")
    print(f"mAP50={metrics.box.map50:.4f} mAP50-95={metrics.box.map:.4f}")


if __name__ == "__main__":
    main()
