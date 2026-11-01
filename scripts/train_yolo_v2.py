"""训练 fire+smoke 双类模型（YOLO26n，RTX 4050 6GB）。

新增参数（默认值与历史行为一致，不影响既有命令）：
``--patience/--scale/--lr0/--cos-lr/--copy-paste/--save-period/--close-mosaic/--warmup-epochs``，
用于远景小目标重训（见 ``docs/far-field-retrain.md``）。
"""
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
    ap.add_argument("--device", default="0", help="训练设备：0 / 0,1 / cpu")
    ap.add_argument("--patience", type=int, default=20, help="early-stop 轮数")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--scale", type=float, default=None,
                    help="随机缩放增益（ultralytics 默认 0.5 → [0.5,1.5]）；越大目标越小")
    ap.add_argument("--lr0", type=float, default=None, help="初始学习率（ultralytics 默认 0.01）")
    ap.add_argument("--cos-lr", action="store_true", help="余弦学习率调度")
    ap.add_argument("--copy-paste", type=float, default=0.0,
                    help="copy-paste 增强概率（>0 才传给 ultralytics）")
    ap.add_argument("--save-period", type=int, default=-1,
                    help="每 N 轮存一次 epochN.pt；1 表示每轮都存（防中断丢进度）")
    ap.add_argument("--close-mosaic", type=int, default=None,
                    help="最后 N 轮关闭 mosaic；默认 min(10, epochs//5)")
    ap.add_argument("--warmup-epochs", type=float, default=None, help="warmup 轮数（默认 3.0）")
    args = ap.parse_args()

    kwargs: dict = {}
    if args.scale is not None:
        kwargs["scale"] = args.scale
    if args.lr0 is not None:
        kwargs["lr0"] = args.lr0
    if args.cos_lr:
        kwargs["cos_lr"] = True
    if args.copy_paste > 0:
        kwargs["copy_paste"] = args.copy_paste
    if args.warmup_epochs is not None:
        kwargs["warmup_epochs"] = args.warmup_epochs
    kwargs["save_period"] = args.save_period
    close_mosaic = (
        args.close_mosaic
        if args.close_mosaic is not None
        else (min(10, args.epochs // 5) if args.epochs > 5 else 0)
    )

    model = YOLO(args.model)
    model.train(
        data=args.data, epochs=args.epochs, imgsz=args.imgsz, batch=args.batch,
        name=args.name, project=str(ROOT / "ai" / "runs"), device=args.device,
        workers=args.workers, patience=args.patience, seed=args.seed, amp=True,
        cache=False, plots=True, val=not args.no_val, fraction=args.fraction,
        mosaic=args.mosaic, close_mosaic=close_mosaic, **kwargs,
    )


if __name__ == "__main__":
    main()
