from __future__ import annotations

import random
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def parse_xml(xml: Path):
    root = ET.parse(xml).getroot()
    width = int(root.findtext("size/width"))
    height = int(root.findtext("size/height"))
    objects = []
    for obj in root.findall("object"):
        name = (obj.findtext("name") or "").strip()
        box = obj.find("bndbox")
        if not name or box is None or width <= 0 or height <= 0:
            continue
        xmin = float(box.findtext("xmin"))
        ymin = float(box.findtext("ymin"))
        xmax = float(box.findtext("xmax"))
        ymax = float(box.findtext("ymax"))
        x_c = ((xmin + xmax) / 2) / width
        y_c = ((ymin + ymax) / 2) / height
        w = (xmax - xmin) / width
        h = (ymax - ymin) / height
        objects.append((name, x_c, y_c, w, h))
    return width, height, objects


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    voc = root / "datasets" / "fire-smoke-voc" / "VOC2020"
    out = root / "datasets" / "fire-smoke-yolo"
    seed = 42
    val_ratio = 0.15

    ann_dir = voc / "Annotations"
    img_dir = voc / "JPEGImages"
    if not ann_dir.is_dir() or not img_dir.is_dir():
        sys.exit("VOC2020 目录结构不正确，请先完成 Task 3")

    labels = sorted(ann_dir.glob("*.xml"))
    random.Random(seed).shuffle(labels)
    val_count = max(1, round(len(labels) * val_ratio))
    val_set = set(labels[:val_count])

    class_names: list[str] = []
    for xml in labels:
        _, _, objects = parse_xml(xml)
        for name, *_ in objects:
            if name not in class_names:
                class_names.append(name)
    class_names.sort()
    class_index = {name: i for i, name in enumerate(class_names)}

    for split in ("train", "val"):
        (out / "images" / split).mkdir(parents=True, exist_ok=True)
        (out / "labels" / split).mkdir(parents=True, exist_ok=True)

    train_count = 0
    for xml in labels:
        split = "val" if xml in val_set else "train"
        stem = xml.stem
        image = None
        for ext in (".jpg", ".jpeg", ".png"):
            cand = img_dir / (stem + ext)
            if cand.is_file():
                image = cand
                break
        if image is None:
            print(f"[跳过] 找不到图片: {xml.name}")
            continue

        _, _, objects = parse_xml(xml)
        lines = []
        for name, x_c, y_c, w, h in objects:
            cls = class_index[name]
            x_c = min(max(x_c, 0.0), 1.0)
            y_c = min(max(y_c, 0.0), 1.0)
            w = min(max(w, 0.0), 1.0)
            h = min(max(h, 0.0), 1.0)
            lines.append(f"{cls} {x_c:.6f} {y_c:.6f} {w:.6f} {h:.6f}")

        (out / "images" / split / image.name).write_bytes(image.read_bytes())
        (out / "labels" / split / f"{stem}.txt").write_text("\n".join(lines), encoding="utf-8")
        if split == "train":
            train_count += 1

    path_text = out.as_posix()
    data_yaml = (
        f'path: "{path_text}"\n'
        f"train: images/train\n"
        f"val: images/val\n"
        f"nc: {len(class_names)}\n"
        f"names: {class_names}\n"
    )
    (out / "data.yaml").write_text(data_yaml, encoding="utf-8")
    print(f"class_names={class_names}")
    print(f"train={train_count} val={len(val_set)}")
    print(f"data.yaml -> {out / 'data.yaml'}")


if __name__ == "__main__":
    main()
