"""数据集规模统计 + 样本拼图 + 分布图（答辩现场可直接跑）。

用法（仓库根目录）：
    python scripts/dataset_card.py
产出：
    docs/dataset-card.md        统计报告（可直接贴进答辩材料）
    docs/dataset-samples.png    64 张样本拼图（红框=明火，橙框=烟雾，灰框=背景/负样本）
    docs/dataset-stats.png      分布图（各数据集图片数 / 类别框数 / 目标尺寸分布）
    ai/runs/dataset-stats.json  机器可读结果
"""
from __future__ import annotations

import json
import random
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
OUT_JSON = ROOT / "ai" / "runs" / "dataset-stats.json"
TRAIN_ROOT = ROOT / "datasets" / "fire-smoke-v2-640"
CLASS_NAMES = {0: "smoke", 1: "fire"}

DATASETS = [
    ("datasets/d-fire", "D-Fire 原始集（VOC 标注，训练来源）"),
    ("datasets/fire-smoke-v2-640", "训练集（预缩放 640，YOLO 标注）"),
    ("datasets/smoke-fire", "SmokeFire 跨域评测集（未参与训练）"),
    ("datasets/extra", "困难负样本（日出/路灯/蒸汽等）"),
    ("datasets/fire-smoke-voc", "首轮单类火灾集（VOC）"),
    ("datasets/fire-smoke-yolo", "首轮单类火灾集（YOLO）"),
]


def count_images(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for p in path.rglob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png"})


def read_list(name: str) -> list[Path]:
    f = TRAIN_ROOT / name
    if not f.is_file():
        return []
    out = []
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        p = Path(line.replace("\\", "/"))
        if not p.is_file():
            # 兼容 Windows 绝对路径从别的机器拷来的情况
            idx = line.replace("\\", "/").find("fire-smoke-v2-640/")
            if idx >= 0:
                p = TRAIN_ROOT / line.replace("\\", "/")[idx + len("fire-smoke-v2-640/"):]
        out.append(p)
    return out


def label_path(img: Path) -> Path:
    return img.parent.parent / "labels" / (img.stem + ".txt")


def split_stats(images: list[Path]) -> dict:
    stats = {
        "images": len(images),
        "with_labels": 0,
        "no_label_negative": 0,
        "boxes": 0,
        "per_class": Counter(),
        "size_buckets": Counter(),
        "min_side_px": [],
    }
    for img in images:
        lbl = label_path(img)
        rows = []
        if lbl.is_file():
            rows = [r for r in lbl.read_text(encoding="utf-8").splitlines() if r.strip()]
        if not rows:
            stats["no_label_negative"] += 1
            continue
        stats["with_labels"] += 1
        for r in rows:
            parts = r.split()
            if len(parts) < 5:
                continue
            cls = int(float(parts[0]))
            w, h = float(parts[3]), float(parts[4])
            stats["per_class"][CLASS_NAMES.get(cls, str(cls))] += 1
            stats["boxes"] += 1
            ratio = w * h
            if ratio < 0.01:
                stats["size_buckets"]["小目标 (<1% 画面)"] += 1
            elif ratio < 0.10:
                stats["size_buckets"]["中目标 (1%~10%)"] += 1
            else:
                stats["size_buckets"]["大目标 (>10%)"] += 1
            try:
                with Image.open(img) as im:
                    iw, ih = im.size
                stats["min_side_px"].append(round(min(w * iw, h * ih), 1))
            except Exception:
                pass
    if stats["min_side_px"]:
        s = sorted(stats["min_side_px"])
        stats["min_side_px_median"] = s[len(s) // 2]
        stats["min_side_px_p10"] = s[max(0, len(s) // 10)]
    stats["per_class"] = dict(stats["per_class"])
    stats["size_buckets"] = dict(stats["size_buckets"])
    stats.pop("min_side_px", None)
    return stats


def make_montage(images: list[Path], out: Path, cols: int = 8, rows: int = 8, cell: int = 128) -> int:
    random.seed(42)
    picked = random.sample(images, min(len(images), cols * rows))
    canvas = Image.new("RGB", (cols * cell, rows * cell), (24, 28, 36))
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 13)
    except Exception:
        font = ImageFont.load_default()
    drawn = 0
    for idx, img in enumerate(picked):
        r, c = divmod(idx, cols)
        x0, y0 = c * cell, r * cell
        try:
            with Image.open(img) as im:
                im = im.convert("RGB")
                im.thumbnail((cell - 4, cell - 4))
                canvas.paste(im, (x0 + 2, y0 + 2))
        except Exception:
            continue
        lbl = label_path(img)
        classes = set()
        if lbl.is_file():
            for line in lbl.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    classes.add(int(float(line.split()[0])))
        color = (229, 72, 77) if 1 in classes else (230, 162, 60) if 0 in classes else (140, 148, 160)
        tag = "fire" if 1 in classes else "smoke" if 0 in classes else "neg"
        draw.rectangle([x0 + 1, y0 + 1, x0 + cell - 2, y0 + cell - 2], outline=color, width=2)
        draw.text((x0 + 5, y0 + cell - 17), tag, fill=color, font=font)
        drawn += 1
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out)
    return drawn


def bar_panel(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, title: str,
              data: dict, color=(35, 161, 107), font=None) -> None:
    draw.text((x, y - 22), title, fill=(40, 48, 60), font=font)
    if not data:
        return
    items = list(data.items())
    max_v = max(v for _, v in items) or 1
    bar_h = max(14, (h - 10) // len(items) - 8)
    for i, (k, v) in enumerate(items):
        yy = y + i * (bar_h + 8)
        bw = int((w - 190) * v / max_v)
        draw.rectangle([x, yy, x + bw, yy + bar_h], fill=color)
        draw.text((x + bw + 8, yy + max(0, bar_h // 2 - 8)), f"{k}: {v:,}", fill=(40, 48, 60), font=font)


def make_stats_panel(all_counts: dict, train: dict, out: Path) -> None:
    W, H = 1280, 760
    canvas = Image.new("RGB", (W, H), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 18)
        big = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 26)
    except Exception:
        font = ImageFont.load_default()
        big = font

    draw.text((40, 24), "FireGuard AI 训练数据规模", fill=(20, 26, 36), font=big)
    draw.text((40, 64), f"训练用图片 {train['images']:,} 张 · 标注框 {train['boxes']:,} 个 · "
                        f"背景（负）样本 {train['no_label_negative']:,} 张", fill=(90, 100, 115), font=font)

    bar_panel(draw, 40, 150, 560, 240, "各数据集图片数", all_counts, (31, 77, 120), font)
    bar_panel(draw, 660, 150, 560, 150, "训练集标注框（按类别）", train["per_class"], (229, 72, 77), font)
    bar_panel(draw, 40, 470, 560, 200, "训练集目标尺寸分布（框面积占画面）",
              train["size_buckets"], (230, 162, 60), font)

    # 关键结论块
    draw.rectangle([660, 470, 1240, 700], outline=(220, 226, 235), width=2)
    draw.text((680, 486), "关键数字", fill=(20, 26, 36), font=big)
    lines = [
        f"训练图：{train['with_labels']:,} 张有标注 + {train['no_label_negative']:,} 张负样本",
        f"总标注框：{train['boxes']:,} 个",
        f"小目标占比：{train['size_buckets'].get('小目标 (<1% 画面)', 0):,} 个框（<1% 画面）",
        f"目标最短边中位数：{train.get('min_side_px_median', '—')} px",
        f"目标最短边 10% 分位：{train.get('min_side_px_p10', '—')} px",
    ]
    for i, line in enumerate(lines):
        draw.text((684, 530 + i * 32), "· " + line, fill=(60, 70, 85), font=font)

    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out)


def main() -> None:
    all_counts = {}
    for rel, _desc in DATASETS:
        n = count_images(ROOT / rel)
        if n:
            all_counts[rel.replace("datasets/", "")] = n

    train_imgs = read_list("train.txt")
    val_imgs = read_list("val.txt")
    test_imgs = read_list("test.txt")
    train = split_stats(train_imgs)
    val = split_stats(val_imgs)
    test = split_stats(test_imgs)

    report = {
        "datasets": all_counts,
        "train": train,
        "val": val,
        "test": test,
        "total_images_all_datasets": sum(all_counts.values()),
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    drawn = make_montage(train_imgs, DOCS / "dataset-samples.png")
    make_stats_panel(all_counts, train, DOCS / "dataset-stats.png")

    print(f"训练集：{train['images']:,} 张（有标注 {train['with_labels']:,} / 负样本 {train['no_label_negative']:,}）")
    print(f"  标注框 {train['boxes']:,} 个 -> {train['per_class']}")
    print(f"  尺寸分布 {train['size_buckets']}")
    print(f"  最短边中位数 {train.get('min_side_px_median')} px，10% 分位 {train.get('min_side_px_p10')} px")
    print(f"验证集 {val['images']:,} 张 / {val['boxes']:,} 框；测试集 {test['images']:,} 张 / {test['boxes']:,} 框")
    print(f"各数据集图片数 {all_counts}")
    print(f"样本拼图 docs/dataset-samples.png（{drawn} 张）")
    print(f"分布图   docs/dataset-stats.png")
    print(f"JSON     {OUT_JSON.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
