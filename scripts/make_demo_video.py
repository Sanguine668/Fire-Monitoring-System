from pathlib import Path
import shutil
import tempfile

import cv2
import numpy as np

root = Path(__file__).resolve().parents[1]
img_dir = root / "datasets" / "fire-smoke-voc" / "VOC2020" / "JPEGImages"
out = root / "storage" / "uploads"
out.mkdir(parents=True, exist_ok=True)
target = out / "demo_fire.mp4"
tmp_target = Path(tempfile.gettempdir()) / "fireguard_demo_fire.mp4"

from ultralytics import YOLO  # noqa: E402

model = YOLO(str(root / "ai" / "runs" / "fire26n" / "weights" / "best.pt"))
selected = []
for p in sorted(img_dir.glob("*.jpg")):
    img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        continue
    result = model.predict(img, imgsz=640, conf=0.4, device="cpu", verbose=False)[0]
    if result.boxes is not None and len(result.boxes):
        selected.append(p)
        if len(selected) >= 24:
            break
images = selected or sorted(img_dir.glob("*.jpg"))[:24]
writer = None
w = h = 0
for p in images:
    img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        continue
    if writer is None:
        h, w = img.shape[:2]
        writer = cv2.VideoWriter(str(tmp_target), cv2.VideoWriter_fourcc(*"mp4v"), 6, (w, h))
    img = cv2.resize(img, (w, h))
    for _ in range(3):
        writer.write(img)
if writer:
    writer.release()
    target.unlink(missing_ok=True)
    shutil.move(str(tmp_target), str(target))
print(target)
