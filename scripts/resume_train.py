"""从 last.pt 断点续训（训练参数由 checkpoint 恢复）。"""
from ultralytics import YOLO

YOLO("ai/runs/fire26n-v2/weights/last.pt").train(resume=True)
