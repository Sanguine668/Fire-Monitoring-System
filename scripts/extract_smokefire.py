"""解压 SmokeFire 分卷合并后的 zip（压缩包中文目录名已损坏，按文件名扁平解压）。"""
from __future__ import annotations

import argparse
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", default="datasets/incoming/SmokeFire.zip")
    ap.add_argument("--out", default="datasets/smoke-fire/raw")
    args = ap.parse_args()
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    count = 0
    with zipfile.ZipFile(ROOT / args.zip) as z:
        for info in z.infolist():
            base = info.filename.rsplit("/", 1)[-1]
            if not base.lower().endswith((".jpg", ".xml")):
                continue
            with z.open(info) as src, open(out / base, "wb") as dst:
                shutil.copyfileobj(src, dst)
            count += 1
    jpg = len(list(out.glob("*.jpg")))
    xml = len(list(out.glob("*.xml")))
    print(f"extracted={count} jpg={jpg} xml={xml} -> {out}")


if __name__ == "__main__":
    main()
