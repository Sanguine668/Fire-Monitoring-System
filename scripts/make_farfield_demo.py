"""从 D-Fire 的连续远景视频帧合成演示视频，便于对比整图与切片推理。"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "datasets" / "d-fire" / "test" / "images"
OUT = ROOT / "storage" / "uploads" / "demo_farfield.mp4"
START, COUNT, FPS = 7718, 150, 10


def main() -> None:
    frames = [SRC / f"AoF{n:05d}.jpg" for n in range(START, START + COUNT)]
    frames = [p for p in frames if p.is_file()]
    first = cv2.imdecode(np.fromfile(str(frames[0]), dtype=np.uint8), cv2.IMREAD_COLOR)
    h, w = first.shape[:2]
    tmp = Path(tempfile.gettempdir()) / "fireguard_farfield.mp4"
    writer = cv2.VideoWriter(str(tmp), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (w, h))
    for p in frames:
        img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            continue
        writer.write(cv2.resize(img, (w, h)))
    writer.release()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(tmp), str(OUT))
    print(f"{OUT}  {len(frames)} 帧  {w}x{h}  {FPS}fps")


if __name__ == "__main__":
    main()
