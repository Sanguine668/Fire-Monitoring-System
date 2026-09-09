"""真实 AI 模型接入点。

当前演示版由 main.py 的 DemoState 生成模拟检测结果。
后续接 YOLO 时，只需实现 detect(frame) 并返回统一结构：
[
  {"type": "fire", "confidence": 0.91, "bbox": [x, y, w, h]},
  {"type": "smoke", "confidence": 0.78, "bbox": [x, y, w, h]},
]

推荐把 RTSP 读取、抽帧、YOLO 推理放到独立 worker，再通过 WebSocket/队列推送到业务层。
"""

class DetectorAdapter:
    def __init__(self, model_path: str | None = None):
        self.model_path = model_path

    def detect(self, frame):
        raise NotImplementedError("Replace DemoState with a real YOLO detector here.")
