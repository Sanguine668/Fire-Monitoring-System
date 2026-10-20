"""把训练/验证/测试图片缩放到长边 640，避免训练时反复解码大图。

Windows 下多进程 DataLoader 会因页文件不足报 WinError 1455，单进程训练时
解码大图是主要瓶颈；预缩放后每轮训练时间可降到几分之一。
YOLO 标签是归一化坐标，缩放不影响标注。
"""
from __future__ import annotations

import argparse
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageFile

ImageFile.LOAD_TRUNCATED_IMAGES = True

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "datasets" / "fire-smoke-v2"
DST = ROOT / "datasets" / "fire-smoke-v2-640"


def convert(src: Path, dst: Path, size: int) -> str:
    if dst.is_file():
        return "skip"
    dst.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        im = im.convert("RGB")
        im.thumbnail((size, size), Image.LANCZOS)
        im.save(dst, "JPEG", quality=92, optimize=True)
    return "ok"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=640)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    for split in ("train", "val", "test"):
        files = [Path(p) for p in (SRC / f"{split}.txt").read_text(encoding="utf-8").splitlines() if p.strip()]
        out_dir = DST / split
        (out_dir / "images").mkdir(parents=True, exist_ok=True)
        (out_dir / "labels").mkdir(parents=True, exist_ok=True)
        jobs = []
        for p in files:
            dst_img = out_dir / "images" / (p.stem + ".jpg")
            dst_lab = out_dir / "labels" / (p.stem + ".txt")
            src_lab = p.parent.parent / "labels" / (p.stem + ".txt")
            jobs.append((p, dst_img, src_lab, dst_lab))

        def run(job):
            p, dst_img, src_lab, dst_lab = job
            status = convert(p, dst_img, args.size)
            if not dst_lab.is_file():
                shutil.copyfile(src_lab, dst_lab)
            return status

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            results = list(pool.map(run, jobs))
        print(f"{split}: {len(files)} 张，新转换 {results.count('ok')}，已存在 {results.count('skip')}")

    lists = {}
    for split in ("train", "val", "test"):
        items = sorted((DST / split / "images").glob("*.jpg"))
        list_path = DST / f"{split}.txt"
        list_path.write_text("\n".join(p.as_posix() for p in items), encoding="utf-8")
        lists[split] = list_path
    (DST / "data.yaml").write_text(
        "path: {p}\ntrain: {t}\nval: {v}\ntest: {s}\nnames:\n  0: smoke\n  1: fire\n".format(
            p=DST.as_posix(),
            t=lists["train"].as_posix(),
            v=lists["val"].as_posix(),
            s=lists["test"].as_posix(),
        ),
        encoding="utf-8",
    )
    print("data.yaml:", DST / "data.yaml")


if __name__ == "__main__":
    main()
