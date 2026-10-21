"""从 last.pt 断点续训（训练参数由 checkpoint 恢复）。"""
import ctypes

from ultralytics import YOLO

# 训练期间阻止系统空闲休眠（合盖休眠仍需在电源设置里单独处理）
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)

YOLO("ai/runs/fire26n-v2/weights/last.pt").train(resume=True)
