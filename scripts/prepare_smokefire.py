"""体检 SmokeFire VOC 数据并转成 YOLO，供独立评测或后续微调。"""
from __future__ import annotations

import json
import os
import random
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "datasets" / "smoke-fire" / "raw"
OUT = ROOT / "datasets" / "smoke-fire"
CLASS_MAP = {"smoke": 0, "fire": 1, "flame": 1}


def parse_xml(path: Path) -> tuple[int, int, list[tuple[int, float, float, float, float]]]:
    root = ET.parse(path).getroot()
    size = root.find("size")
    w = int(float(size.findtext("width")))
    h = int(float(size.findtext("height")))
    rows = []
    for obj in root.findall("object"):
        name = (obj.findtext("name") or "").strip().lower()
        if name not in CLASS_MAP:
            continue
        box = obj.find("bndbox")
        x1 = max(0.0, min(w, float(box.findtext("xmin"))))
        y1 = max(0.0, min(h, float(box.findtext("ymin"))))
        x2 = max(0.0, min(w, float(box.findtext("xmax"))))
        y2 = max(0.0, min(h, float(box.findtext("ymax"))))
        if x2 <= x1 or y2 <= y1:
            continue
        rows.append((CLASS_MAP[name], x1, y1, x2, y2))
    return w, h, rows


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "images").mkdir(exist_ok=True)
    (OUT / "labels").mkdir(exist_ok=True)
    xmls = sorted(RAW.glob("*.xml"))
    jpgs = sorted(RAW.glob("*.jpg"))
    class_boxes = Counter()
    class_images = Counter()
    empty = missing_img = bad = 0
    labeled: list[Path] = []

    for xml in xmls:
        img = RAW / (xml.stem + ".jpg")
        if not img.is_file():
            missing_img += 1
            continue
        try:
            w, h, rows = parse_xml(xml)
        except Exception:
            bad += 1
            continue
        present = {c for c, *_ in rows}
        for c in present:
            class_images[c] += 1
        for c, *_ in rows:
            class_boxes[c] += 1
        if not rows:
            empty += 1
        lines = []
        for c, x1, y1, x2, y2 in rows:
            lines.append(
                f"{c} {((x1+x2)/2/w):.6f} {((y1+y2)/2/h):.6f} "
                f"{(x2-x1)/w:.6f} {(y2-y1)/h:.6f}"
            )
        label = OUT / "labels" / (xml.stem + ".txt")
        label.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        dst_img = OUT / "images" / (xml.stem + ".jpg")
        if not dst_img.exists():
            os.link(img, dst_img)
        labeled.append(dst_img)

    report = {
        "jpg": len(jpgs),
        "xml": len(xmls),
        "labeled": len(labeled),
        "empty_xml": empty,
        "missing_image": missing_img,
        "bad_xml": bad,
        "class_images": {"smoke": class_images[0], "fire_or_flame": class_images[1]},
        "class_boxes": {"smoke": class_boxes[0], "fire_or_flame": class_boxes[1]},
    }
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    random.Random(42).shuffle(labeled)
    n = len(labeled)
    n_val = max(1, int(n * 0.1))
    n_test = max(1, int(n * 0.1))
    val, test, train = labeled[:n_val], labeled[n_val:n_val + n_test], labeled[n_val + n_test:]
    for name, files in (("train", train), ("val", val), ("test", test), ("eval", labeled)):
        (OUT / f"{name}.txt").write_text("\n".join(p.as_posix() for p in files), encoding="utf-8")
    (OUT / "data.yaml").write_text(
        f"path: {OUT.as_posix()}\ntrain: {(OUT/'train.txt').as_posix()}\n"
        f"val: {(OUT/'val.txt').as_posix()}\ntest: {(OUT/'test.txt').as_posix()}\n"
        "names:\n  0: smoke\n  1: fire\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"train={len(train)} val={len(val)} test={len(test)} eval={len(labeled)}")


if __name__ == "__main__":
    main()
