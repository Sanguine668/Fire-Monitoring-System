"""合成混合场景演示视频：非火灾/误导场景 + 真实火情片段。"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
EXTRA = ROOT / "datasets" / "extra"
FIRE = ROOT / "storage" / "uploads" / "demo_fire.mp4"
OUT = ROOT / "storage" / "uploads" / "demo_mixed.mp4"
W, H, FPS = 1280, 720, 10
HOLD = 15  # 每张图片 1.5 秒


def fit(frame: np.ndarray) -> np.ndarray:
    ih, iw = frame.shape[:2]
    scale = min(W / iw, H / ih)
    nw, nh = max(1, int(iw * scale)), max(1, int(ih * scale))
    resized = cv2.resize(frame, (nw, nh))
    canvas = np.full((H, W, 3), (18, 18, 18), dtype=np.uint8)
    x, y = (W - nw) // 2, (H - nh) // 2
    canvas[y:y + nh, x:x + nw] = resized
    return canvas


def read_image(path: Path) -> np.ndarray:
    with Image.open(path) as im:
        return np.array(im.convert("RGB"))[:, :, ::-1].copy()


def write_image(writer, path: Path) -> None:
    frame = fit(read_image(path))
    for _ in range(HOLD):
        writer.write(frame)


def write_fire(writer, seconds: float) -> None:
    cap = cv2.VideoCapture(str(FIRE))
    if not cap.isOpened():
        return
    for i in range(int(seconds * FPS)):
        cap.set(cv2.CAP_PROP_POS_MSEC, (i / FPS) * 1000)
        ok, frame = cap.read()
        if not ok:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = cap.read()
        if ok:
            writer.write(fit(frame))
    cap.release()


def main() -> None:
    sunrise = sorted((EXTRA / "sunrise").glob("*.jpeg"))[:4]
    street = sorted(EXTRA.glob("street_*.jpg"))[:2]
    steam = sorted(EXTRA.glob("steam_*.jpg"))[:4]
    other = sorted((EXTRA / "other_neg").rglob("*.jpg"))[:3]

    tmp = Path(tempfile.gettempdir()) / "fireguard_mixed.mp4"
    writer = cv2.VideoWriter(str(tmp), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
    for p in sunrise + street + steam + other:
        write_image(writer, p)
    write_fire(writer, 6)
    for p in sunrise[:2]:
        write_image(writer, p)
    write_fire(writer, 4)
    writer.release()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(tmp), str(OUT))
    print(f"{OUT}  {W}x{H}  {FPS}fps  {round(OUT.stat().st_size/1024/1024, 2)}MB")


if __name__ == "__main__":
    main()
