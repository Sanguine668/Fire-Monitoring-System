"""全量数据集分页拼图（每张图都出现，不是抽样）。

用法（仓库根目录）：
    python scripts/dataset_sheets.py                 # 训练/验证/测试 + 4 个旁路数据集
    python scripts/dataset_sheets.py --only-catalog   # 只画 fire-smoke-v2-640 三个划分
    python scripts/dataset_sheets.py --splits train,val
    python scripts/dataset_sheets.py --thumb 32 --cols 80 --only-catalog

产出：
    docs/samples/<split>-01.png, <split>-02.png, ...   fire-smoke-v2-640 各划分
    docs/samples/smoke-fire-01.png, extra-01.png, ...   旁路数据集
    ai/runs/dataset-sheets.json                        机器可读清单（stats 开启时）

设计要点：
* 缩略图 40×40，64 列 → 画板宽 2560 px；每页图数按总数均分到
  ``ceil(n / (cols*rows))`` 页（避免最后一页只剩几十张），单页高 ≤ ~1700 px。
* 边框颜色：红=有明火框（class 1 fire），橙=有烟雾框（class 0 smoke），
  灰=背景/负样本（无标注文件或标注为空）。
* 页内顺序默认按固定种子打乱（``--order shuffle --seed 42``，可复现），
  否则 train.txt 按来源成块排列，第 1 页 2,215 张里 2,209 张是雨天负样本，
  整页几乎全灰，答辩时无法在同一页指出红/橙/灰三种边框。
  需要原始顺序时加 ``--order list``；两种顺序覆盖的图片完全相同。
* 用 PIL 的 ``draft()`` 让 JPEG 按 1/8 解码，再 ``ImageOps.fit`` 到 40×40，
  全程不解全分辨率；配合线程池并行读盘，2 万张图的拼图在几分钟内完成。
* 复用 ``scripts/dataset_card.py`` 的 read_list / label_path / split_stats，
  保证与统计报告口径一致；统计在 --stats（默认开，--no-stats 关闭）时调用，
  且排在绘制之后，此时文件已在系统缓存里，额外开销很小。
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
OUT_JSON = ROOT / "ai" / "runs" / "dataset-sheets.json"
DATASETS_ROOT = ROOT / "datasets"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dataset_card import label_path, read_list, split_stats  # noqa: E402

# 边框配色（与 docs/dataset-samples.png 一致）
FIRE = (229, 72, 77)
SMOKE = (230, 162, 60)
NEGATIVE = (140, 148, 160)
BG = (16, 20, 27)
HEADER_H = 30
FONT_CANDIDATES = (
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/simhei.ttf",
)

V2_CLASSES = {0: "smoke", 1: "fire"}          # fire-smoke-v2-640 / smoke-fire
YOLO_FIRE_ONLY = {0: "fire"}                  # fire-smoke-yolo（首轮单类）
VOC_CLASSES = {"fire": "fire", "smoke": "smoke"}  # fire-smoke-voc

SPLIT_TITLES = {"train": "训练集", "val": "验证集", "test": "测试集"}


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in FONT_CANDIDATES:
        p = Path(candidate)
        if p.is_file():
            try:
                return ImageFont.truetype(str(p), size)
            except OSError:
                continue
    return ImageFont.load_default()


def _cells(n: int, cols: int, rows: int) -> tuple[int, int]:
    """返回 (页数, 每页图数)，均分页，单页不超过 cols*rows。"""
    if n <= 0:
        return 0, 0
    pages = max(1, math.ceil(n / (cols * rows)))
    return pages, math.ceil(n / pages)


@dataclass
class SheetJob:
    key: str
    title: str
    images: list[Path]
    classes_of: Callable[[Path], set[str]]
    thumb: int = 40
    cols: int = 64
    rows: int = 40


def yolo_classes_of(path: Path, labels_root: Path, images_root: Path,
                    class_map: dict[int, str]) -> set[str]:
    rel = path.relative_to(images_root)
    lbl = (labels_root / rel).with_suffix(".txt")
    found: set[str] = set()
    if not lbl.is_file():
        return found
    try:
        rows = lbl.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return found
    for row in rows:
        parts = row.split()
        if len(parts) < 5:
            continue
        try:
            cls = int(float(parts[0]))
        except ValueError:
            continue
        name = class_map.get(cls)
        if name:
            found.add(name)
    return found


def build_catalog_jobs(splits: list[str], thumb: int, cols: int, rows: int,
                       limit: int) -> list[SheetJob]:
    jobs: list[SheetJob] = []
    for split in splits:
        images = read_list(f"{split}.txt")
        if limit:
            images = images[:limit]
        if not images:
            print(f"[skip] {split}: 图片列表为空", file=sys.stderr)
            continue
        jobs.append(
            SheetJob(
                key=split,
                title=f"{SPLIT_TITLES.get(split, split)} {split}",
                images=images,
                classes_of=_classes_from_dataset_card_label,
                thumb=thumb,
                cols=cols,
                rows=rows,
            )
        )
    return jobs


def _classes_from_dataset_card_label(path: Path) -> set[str]:
    """读 YOLO 标注（复用 dataset_card.label_path），返回出现过的类别名集合。"""
    found: set[str] = set()
    lbl = label_path(path)
    if not lbl.is_file():
        return found
    try:
        rows = lbl.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return found
    for row in rows:
        parts = row.split()
        if len(parts) < 5:
            continue
        try:
            name = V2_CLASSES.get(int(float(parts[0])))
        except ValueError:
            continue
        if name:
            found.add(name)
    return found


def _voc_classes_of(path: Path, annotations: Path) -> set[str]:
    xml = annotations / (path.stem + ".xml")
    found: set[str] = set()
    if not xml.is_file():
        return found
    try:
        root = ET.parse(xml).getroot()
    except (ET.ParseError, OSError):
        return found
    for obj in root.findall("object"):
        name = (obj.findtext("name") or "").strip().lower()
        mapped = VOC_CLASSES.get(name)
        if mapped:
            found.add(mapped)
    return found


def build_side_jobs(thumb: int, cols: int, rows: int, limit: int) -> list[SheetJob]:
    jobs: list[SheetJob] = []

    smoke_root = DATASETS_ROOT / "smoke-fire"
    smoke_imgs_root = smoke_root / "images"
    if smoke_imgs_root.is_dir():
        images = sorted(p for p in smoke_imgs_root.rglob("*.jpg") if p.is_file())
        if limit:
            images = images[:limit]
        labels_root = smoke_root / "labels"
        jobs.append(SheetJob(
            key="smoke-fire",
            title="smoke-fire 跨域评测集",
            images=images,
            classes_of=lambda p: yolo_classes_of(p, labels_root, smoke_imgs_root, V2_CLASSES),
            thumb=thumb, cols=cols, rows=rows,
        ))

    extra_root = DATASETS_ROOT / "extra"
    if extra_root.is_dir():
        images = sorted(p for p in extra_root.rglob("*")
                        if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png"})
        if limit:
            images = images[:limit]
        jobs.append(SheetJob(
            key="extra",
            title="extra 困难负样本",
            images=images,
            classes_of=lambda p: set(),  # 目录内无标注文件，全部按负样本着色
            thumb=thumb, cols=cols, rows=rows,
        ))

    yolo_root = DATASETS_ROOT / "fire-smoke-yolo"
    yolo_imgs_root = yolo_root / "images"
    if yolo_imgs_root.is_dir():
        images = sorted(p for p in yolo_imgs_root.rglob("*")
                        if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png"})
        if limit:
            images = images[:limit]
        labels_root = yolo_root / "labels"
        jobs.append(SheetJob(
            key="fire-smoke-yolo",
            title="fire-smoke-yolo 首轮火灾集",
            images=images,
            classes_of=lambda p: yolo_classes_of(p, labels_root, yolo_imgs_root, YOLO_FIRE_ONLY),
            thumb=thumb, cols=cols, rows=rows,
        ))

    voc_root = DATASETS_ROOT / "fire-smoke-voc" / "VOC2020"
    voc_imgs_root = voc_root / "JPEGImages"
    if voc_imgs_root.is_dir():
        images = sorted(p for p in voc_imgs_root.rglob("*")
                        if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png"})
        if limit:
            images = images[:limit]
        annotations = voc_root / "Annotations"
        jobs.append(SheetJob(
            key="fire-smoke-voc",
            title="fire-smoke-voc 首轮火灾集",
            images=images,
            classes_of=lambda p: _voc_classes_of(p, annotations),
            thumb=thumb, cols=cols, rows=rows,
        ))

    return jobs


def _make_cell(path: Path, classes_of: Callable[[Path], set[str]],
               thumb: int) -> tuple[Image.Image | None, tuple[int, int, int]]:
    try:
        classes = classes_of(path)
    except Exception:  # 标注损坏不应中断整页
        classes = set()
    color = FIRE if "fire" in classes else SMOKE if "smoke" in classes else NEGATIVE
    try:
        with Image.open(path) as im:
            im.draft("RGB", (thumb * 2, thumb * 2))  # JPEG 1/8 解码，避免全分辨率
            rgb = im.convert("RGB")
            cell = ImageOps.fit(rgb, (thumb, thumb), Image.Resampling.BILINEAR)
        return cell, color
    except Exception:
        return None, color


def _disp_len(text: str) -> int:
    return sum(2 if ord(ch) > 0x2E7F else 1 for ch in text)


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _disp_len(text))


def _draw_header(draw: ImageDraw.ImageDraw, width: int, title: str, page: int,
                 pages: int, start: int, end: int, total: int, font) -> None:
    draw.rectangle([0, 0, width, HEADER_H - 1], fill=(20, 24, 32))
    left = f"{title} · 第 {page}/{pages} 页 · 图 {start:,}–{end:,} / {total:,}"
    draw.text((10, 5), left, font=font, fill=(232, 236, 244))

    legend = [("明火", FIRE), ("烟雾", SMOKE), ("负样本", NEGATIVE)]
    gap = 16
    seg_w = 12 + 4 + max(draw.textlength(label, font=font) for label, _ in legend)
    total_w = seg_w * len(legend) + gap * (len(legend) - 1)
    x = width - 12 - total_w
    if x > 10 + draw.textlength(left, font=font) + 12:
        for label, color in legend:
            draw.rectangle([x, HEADER_H // 2 - 6, x + 12, HEADER_H // 2 + 6], fill=color)
            draw.text((x + 16, 5), label, font=font, fill=(210, 216, 228))
            x += seg_w + gap


def render_job(job: SheetJob, out_dir: Path, workers: int, show_index: bool,
               font_header, font_index) -> list[dict]:
    n = len(job.images)
    pages, per_page = _cells(n, job.cols, job.rows)
    out_dir.mkdir(parents=True, exist_ok=True)

    pages_out: list[dict] = []
    for page in range(1, pages + 1):
        chunk = job.images[(page - 1) * per_page: page * per_page]
        rows_used = math.ceil(len(chunk) / job.cols)
        width = job.cols * job.thumb
        height = HEADER_H + rows_used * job.thumb
        canvas = Image.new("RGB", (width, height), BG)
        draw = ImageDraw.Draw(canvas)

        start = (page - 1) * per_page + 1
        end = start + len(chunk) - 1
        _draw_header(draw, width, job.title, page, pages, start, end, n, font_header)

        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            cells = list(pool.map(
                lambda p: _make_cell(p, job.classes_of, job.thumb), chunk))
        failed = 0
        for i, (cell, color) in enumerate(cells):
            row, col = divmod(i, job.cols)
            x, y = col * job.thumb, HEADER_H + row * job.thumb
            if cell is not None:
                canvas.paste(cell, (x, y))
            else:
                failed += 1
                draw.rectangle([x, y, x + job.thumb - 1, y + job.thumb - 1],
                               fill=(58, 22, 26))
                draw.line([x + 8, y + 8, x + job.thumb - 9, y + job.thumb - 9],
                          fill=FIRE, width=2)
                draw.line([x + job.thumb - 9, y + 8, x + 8, y + job.thumb - 9],
                          fill=FIRE, width=2)
            draw.rectangle([x, y, x + job.thumb - 1, y + job.thumb - 1],
                           outline=color, width=2)
            if show_index:
                draw.text((x + 3, y + 2), str(start + i), font=font_index,
                          fill=(255, 255, 255))

        out = out_dir / f"{job.key}-{page:02d}.png"
        canvas.save(out, compress_level=6)
        elapsed = time.perf_counter() - t0
        pages_out.append({
            "page": page,
            "file": str(out.relative_to(ROOT)).replace("\\", "/"),
            "images": len(chunk),
            "first": start,
            "last": end,
            "failed": failed,
            "width": width,
            "height": height,
        })
        print(f"  [{page}/{pages}] {pages_out[-1]['file']}  "
              f"{len(chunk):,} 张  图 {start:,}–{end:,}  {width}×{height}  "
              f"{elapsed:.1f}s" + (f"  failed={failed}" if failed else ""), flush=True)
    return pages_out


def order_images(images: list[Path], key: str, mode: str, seed: int) -> list[Path]:
    """固定种子打乱（默认），保证可复现；--order list 保留原始列表顺序。"""
    if mode == "list":
        return images
    out = list(images)
    random.Random(f"{seed}:{key}").shuffle(out)
    return out


def collect_old_sheets(out_dir: Path, keys: list[str]) -> int:
    removed = 0
    for key in keys:
        for old in out_dir.glob(f"{key}-*.png"):
            try:
                old.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def print_manifest(rows: list[dict]) -> None:
    headers = ["数据集", "图片", "页数", "路径模式"]
    widths = [18, 8, 6, 34]
    print()
    print(_pad(headers[0], widths[0]) + headers[1].rjust(widths[1])
          + headers[2].rjust(widths[2]) + "  " + headers[3])
    print("-" * (sum(widths) + 2 + 6))
    for row in rows:
        print(_pad(row["key"], widths[0])
              + f"{row['images']:,}".rjust(widths[1])
              + f"{row['sheets']}".rjust(widths[2])
              + "  " + row["pattern"])
    print("-" * (sum(widths) + 2 + 6))
    print(f"合计 {sum(r['images'] for r in rows):,} 张 · {sum(r['sheets'] for r in rows)} 页")


def print_stats(stats: dict[str, dict]) -> None:
    print("\n规模统计（复用 dataset_card.split_stats）：")
    for split in ("train", "val", "test"):
        s = stats.get(split)
        if not s:
            continue
        small = s["size_buckets"].get("小目标 (<1% 画面)", 0)
        share = (small / s["boxes"] * 100) if s["boxes"] else 0.0
        print(f"  {split:<5} 图片 {s['images']:,}（有标注 {s['with_labels']:,} / "
              f"负样本 {s['no_label_negative']:,}）· 标注框 {s['boxes']:,} "
              f"{s['per_class']} · 小目标 {small:,}（{share:.1f}%）· "
              f"最短边中位数 {s.get('min_side_px_median')} px / "
              f"10% 分位 {s.get('min_side_px_p10')} px")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="全量数据集分页拼图")
    parser.add_argument("--splits", default="train,val,test",
                        help="逗号分隔，默认 train,val,test")
    parser.add_argument("--only-catalog", action="store_true",
                        help="只画 fire-smoke-v2-640 三个划分，跳过旁路数据集")
    parser.add_argument("--thumb", type=int, default=40, help="缩略图边长（默认 40）")
    parser.add_argument("--cols", type=int, default=64, help="每行图片数（默认 64）")
    parser.add_argument("--rows", type=int, default=40, help="每页最大行数（默认 40）")
    parser.add_argument("--side-thumb", type=int, default=40, help="旁路数据集缩略图边长")
    parser.add_argument("--side-cols", type=int, default=40, help="旁路数据集每行列数")
    parser.add_argument("--side-rows", type=int, default=30, help="旁路数据集每页最大行数")
    parser.add_argument("--workers", type=int, default=8, help="解码线程数")
    parser.add_argument("--index", action="store_true", help="在每格左上角画序号（默认关）")
    parser.add_argument("--order", choices=("shuffle", "list"), default="shuffle",
                        help="页内顺序：shuffle=固定种子打乱（默认），list=按列表原序")
    parser.add_argument("--seed", type=int, default=42, help="打乱种子（默认 42）")
    parser.add_argument("--stats", dest="stats", action="store_true", default=True,
                        help="绘制后复算 split_stats（默认开）")
    parser.add_argument("--no-stats", dest="stats", action="store_false")
    parser.add_argument("--limit", type=int, default=0, help="调试：每个数据集只取前 N 张")
    parser.add_argument("--out", default="docs/samples", help="输出目录")
    args = parser.parse_args(argv)

    if args.thumb < 8 or args.cols < 8 or args.rows < 1:
        parser.error("--thumb/--cols 至少 8，--rows 至少 1")
    splits = [s.strip() for s in args.splits.split(",") if s.strip()]
    invalid = [s for s in splits if s not in SPLIT_TITLES]
    if invalid:
        parser.error(f"未知划分: {invalid}（可选 train,val,test）")

    out_dir = (ROOT / args.out) if not Path(args.out).is_absolute() else Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    jobs = build_catalog_jobs(splits, args.thumb, args.cols, args.rows, args.limit)
    if not args.only_catalog:
        jobs += build_side_jobs(args.side_thumb, args.side_cols, args.side_rows, args.limit)

    for job in jobs:  # 默认每页都混有红/橙/灰，便于现场讲解
        job.images = order_images(job.images, job.key, args.order, args.seed)

    removed = collect_old_sheets(out_dir, [j.key for j in jobs])
    if removed:
        print(f"清理旧拼图 {removed} 张")

    font_header = load_font(16)
    font_index = load_font(10)
    order_note = (f"固定种子打乱 seed={args.seed}" if args.order == "shuffle"
                  else "列表原序")
    print(f"\n配置：缩略图 {args.thumb}px · {args.cols} 列/行 · 页内{order_note} · "
          f"{args.workers} 线程")

    t_start = time.perf_counter()
    manifest: list[dict] = []
    for job in jobs:
        print(f"\n[{job.key}] {job.title}：{len(job.images):,} 张 · "
              f"{job.thumb}px × {job.cols} 列", flush=True)
        t0 = time.perf_counter()
        pages = render_job(job, out_dir, args.workers, args.index, font_header, font_index)
        pattern = f"{args.out.rstrip('/').replace(chr(92), '/')}/{job.key}-NN.png"
        manifest.append({
            "key": job.key,
            "title": job.title,
            "images": len(job.images),
            "sheets": len(pages),
            "pattern": pattern,
            "seconds": round(time.perf_counter() - t0, 1),
            "pages": pages,
        })

    print_manifest(manifest)

    stats: dict[str, dict] = {}
    if args.stats:
        for split in splits:
            images = read_list(f"{split}.txt")
            if not images:
                continue
            t0 = time.perf_counter()
            stats[split] = split_stats(images)
            print(f"\n[stats] {split}: {len(images):,} 张 "
                  f"（{time.perf_counter() - t0:.1f}s）", flush=True)
        print_stats(stats)

    if args.stats:
        OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
        OUT_JSON.write_text(json.dumps({
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "thumb": args.thumb,
            "cols": args.cols,
            "rows": args.rows,
            "order": args.order,
            "seed": args.seed,
            "sheets": manifest,
            "stats": stats,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n清单 {OUT_JSON.relative_to(ROOT)}")

    total_images = sum(m["images"] for m in manifest)
    total_pages = sum(m["sheets"] for m in manifest)
    elapsed = time.perf_counter() - t_start
    print(f"\n完成：{total_images:,} 张图 / {total_pages} 页 / {elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
