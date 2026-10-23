"""初始化本地演示环境：复制演示视频、建库、添加视频源，可选补演示历史。"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app import db  # noqa: E402

SAMPLES = ROOT / "samples"
UPLOADS = ROOT / "storage" / "uploads"
CAMERAS = [
    ("demo_fire", "file", "storage/uploads/demo_fire.mp4", "演示", 1),
    ("混合场景演示", "file", "storage/uploads/demo_mixed.mp4", "演示", 1),
    ("远景演示", "file", "storage/uploads/demo_farfield.mp4", "演示", 1),
    ("Phone-IPWebcam", "http", "http://127.0.0.1:8080/video", "手机模拟", 0),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-history", action="store_true", help="补最近 7 天演示告警趋势")
    ap.add_argument("--overwrite", action="store_true", help="覆盖已存在的演示视频")
    args = ap.parse_args()

    UPLOADS.mkdir(parents=True, exist_ok=True)
    (ROOT / "storage" / "snapshots").mkdir(parents=True, exist_ok=True)
    copied = 0
    for src in sorted(SAMPLES.glob("*.mp4")):
        dst = UPLOADS / src.name
        if args.overwrite or not dst.exists():
            shutil.copy2(src, dst)
            copied += 1

    db.init_db()
    existing = {camera["name"] for camera in db.list_cameras()}
    added = 0
    for name, source_type, source, location, loop in CAMERAS:
        if name in existing:
            continue
        db.insert_camera(name, source_type, source, location, loop)
        added += 1

    if args.with_history:
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "seed_demo_alarm_history.py")],
            cwd=ROOT,
            check=False,
        )

    print(f"演示视频复制 {copied} 个，视频源新增 {added} 个")
    print("下一步：")
    print("  $env:FIREGUARD_DEVICE='0'")
    print("  ai\\.venv\\Scripts\\python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000")
    print("  浏览器打开 http://127.0.0.1:8000")


if __name__ == "__main__":
    main()
