"""数据集质量体检：精确重复、近重复、分辨率、目标大小、清晰度与标注统计。"""
from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
VOC = ROOT / "datasets" / "fire-smoke-voc" / "VOC2020"
IMG_DIR = VOC / "JPEGImages"
ANN_DIR = VOC / "Annotations"
OUT_DIR = ROOT / "docs" / "课程任务" / "数据集质量报告"


def dhash(path: Path, size: int = 8) -> int:
    with Image.open(path) as im:
        gray = im.convert("L").resize((size + 1, size), Image.LANCZOS)
    arr = np.asarray(gray, dtype=np.int16)
    bits = (arr[:, 1:] > arr[:, :-1]).flatten()
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return value


def popcount_matrix(hashes: np.ndarray) -> np.ndarray:
    xor = hashes[:, None] ^ hashes[None, :]
    bits = np.unpackbits(xor.view(np.uint8).reshape(len(hashes), len(hashes), 8), axis=2)
    return bits.sum(axis=2)


class UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    images = sorted(IMG_DIR.glob("*.jpg"))
    md5_groups: dict[str, list[str]] = {}
    hashes = []
    sizes = []
    sharpness = []
    brightness = []
    box_areas = []
    boxes_per_image = []
    class_counter: Counter[str] = Counter()

    for path in images:
        data = path.read_bytes()
        md5_groups.setdefault(hashlib.md5(data).hexdigest(), []).append(path.name)
        hashes.append(dhash(path))
        with Image.open(path) as im:
            w, h = im.size
        sizes.append((w, h))
        frame = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame is not None else np.zeros((2, 2), np.uint8)
        sharpness.append(float(cv2.Laplacian(gray, cv2.CV_64F).var()))
        brightness.append(float(gray.mean()))

        xml = ANN_DIR / f"{path.stem}.xml"
        n_box = 0
        if xml.is_file():
            for obj in ET.parse(xml).getroot().findall("object"):
                name = (obj.findtext("name") or "unknown").strip()
                class_counter[name] += 1
                box = obj.find("bndbox")
                if box is None:
                    continue
                x1 = float(box.findtext("xmin")); y1 = float(box.findtext("ymin"))
                x2 = float(box.findtext("xmax")); y2 = float(box.findtext("ymax"))
                box_areas.append((abs(x2 - x1) * abs(y2 - y1), w * h))
                n_box += 1
        boxes_per_image.append(n_box)

    exact_dupes = {k: v for k, v in md5_groups.items() if len(v) > 1}
    hashes_arr = np.array(hashes, dtype=np.uint64)
    dist = popcount_matrix(hashes_arr)
    uf = UnionFind(len(images))
    threshold = 6
    ys, xs = np.where(np.triu(dist <= threshold, k=1))
    for a, b in zip(ys.tolist(), xs.tolist()):
        uf.union(a, b)
    groups: dict[int, list[int]] = {}
    for i in range(len(images)):
        groups.setdefault(uf.find(i), []).append(i)
    near_groups = [sorted(v) for v in groups.values() if len(v) > 1]
    near_groups.sort(key=len, reverse=True)

    areas = np.array([a for a, _ in box_areas], dtype=float)
    img_areas = np.array([t for _, t in box_areas], dtype=float)
    rel = areas / np.maximum(img_areas, 1)
    small = int((areas < 32 * 32).sum())
    medium = int(((areas >= 32 * 32) & (areas < 96 * 96)).sum())
    large = int((areas >= 96 * 96).sum())

    widths = np.array([w for w, _ in sizes])
    heights = np.array([h for _, h in sizes])
    sharp = np.array(sharpness)
    bright = np.array(brightness)

    report = {
        "images": len(images),
        "boxes": int(sum(class_counter.values())),
        "classes": dict(class_counter),
        "exact_duplicate_groups": len(exact_dupes),
        "exact_duplicate_images": int(sum(len(v) - 1 for v in exact_dupes.values())),
        "near_duplicate_groups": len(near_groups),
        "near_duplicate_images": int(sum(len(v) - 1 for v in near_groups)),
        "near_duplicate_top": [
            {"size": len(g), "images": [images[i].name for i in g[:12]]} for g in near_groups[:20]
        ],
        "width": {"min": int(widths.min()), "max": int(widths.max()), "median": int(np.median(widths)),
                  "lt640": int((widths < 640).sum())},
        "height": {"min": int(heights.min()), "max": int(heights.max()), "median": int(np.median(heights))},
        "box_area_px": {"small_lt32x32": small, "medium_32to96": medium, "large_ge96": large,
                         "small_ratio": round(small / max(len(areas), 1), 3),
                         "median_px": round(float(np.median(areas)), 1)},
        "relative_box_area": {"median": round(float(np.median(rel)), 5),
                               "lt_0.5pct": int((rel < 0.005).sum()),
                               "ge_5pct": int((rel >= 0.05).sum())},
        "boxes_per_image": {"median": float(np.median(boxes_per_image)),
                             "max": int(max(boxes_per_image)),
                             "empty": int(sum(1 for n in boxes_per_image if n == 0))},
        "sharpness_laplacian": {"median": round(float(np.median(sharp)), 1),
                                 "lt50_blurry": int((sharp < 50).sum())},
        "brightness": {"median": round(float(np.median(bright)), 1),
                        "lt40_dark": int((bright < 40).sum()),
                        "gt200_overexposed": int((bright > 200).sum())},
    }
    (OUT_DIR / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# 烟火训练集质量体检报告",
        "",
        f"- 图片总数：{report['images']}，标注框总数：{report['boxes']}，类别：{report['classes']}",
        f"- 精确重复：{report['exact_duplicate_groups']} 组，冗余图片 {report['exact_duplicate_images']} 张",
        f"- 近重复（dHash 距离≤6）：{report['near_duplicate_groups']} 组，冗余图片 {report['near_duplicate_images']} 张",
        f"- 分辨率：宽度 {report['width']['min']}~{report['width']['max']}（中位数 {report['width']['median']}），"
        f"其中 {report['width']['lt640']} 张宽度小于 640",
        f"- 目标框面积：小目标(<32×32) {small} 个（{report['box_area_px']['small_ratio']:.1%}）、"
        f"中目标 {medium} 个、大目标 {large} 个；中位面积 {report['box_area_px']['median_px']} 像素",
        f"- 相对面积：中位数 {report['relative_box_area']['median']:.4%}，"
        f"小于图片面积 0.5% 的框 {report['relative_box_area']['lt_0.5pct']} 个，"
        f"大于 5% 的框 {report['relative_box_area']['ge_5pct']} 个",
        f"- 每图目标数：中位数 {report['boxes_per_image']['median']}，最大 {report['boxes_per_image']['max']}，"
        f"无目标图片 {report['boxes_per_image']['empty']} 张",
        f"- 清晰度（Laplacian 方差）：中位数 {report['sharpness_laplacian']['median']}，"
        f"低于 50 的模糊图 {report['sharpness_laplacian']['lt50_blurry']} 张",
        f"- 亮度：中位数 {report['brightness']['median']}，过暗(<40) {report['brightness']['lt40_dark']} 张，"
        f"过曝(>200) {report['brightness']['gt200_overexposed']} 张",
        "",
        "## 近重复组（按组大小排序，最多显示 20 组）",
        "",
    ]
    for g in near_groups[:20]:
        names = "、".join(images[i].name for i in g[:8])
        lines.append(f"- {len(g)} 张：{names}{' …' if len(g) > 8 else ''}")
    lines.append("")
    lines.append("> 详细数据见 report.json；近重复判定使用 8×8 dHash，阈值 6。")
    (OUT_DIR / "数据质量体检报告.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
