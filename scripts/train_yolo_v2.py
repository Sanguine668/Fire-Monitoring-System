"""训练 fire+smoke 双类模型（YOLO26n，RTX 4050 6GB）。"""
from __future__ import annotations

import argparse
from pathlib import Path

from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="yolo26n.pt")
    ap.add_argument("--data", default="datasets/fire-smoke-v2/data.yaml")
    ap.add_argument("--epochs", type=int, default=80)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--fraction", type=float, default=1.0)
    ap.add_argument("--mosaic", type=float, default=1.0)
    ap.add_argument("--no-val", action="store_true", help="训练中不跑验证，结束后单独验证")
    ap.add_argument("--name", default="fire26n-v2")
    args = ap.parse_args()

    model = YOLO(args.model)
    model.train(
        data=args.data, epochs=args.epochs, imgsz=args.imgsz, batch=args.batch,
        name=args.name, project=str(ROOT / "ai" / "runs"), device=0,
        workers=args.workers, patience=20, seed=42, amp=True,
        cache=False, plots=True, val=not args.no_val, fraction=args.fraction,
        mosaic=args.mosaic, close_mosaic=min(10, args.epochs // 5) if args.epochs > 5 else 0,
    )


if __name__ == "__main__":
    main()
