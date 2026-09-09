from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
import xml.etree.ElementTree as ET


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    voc = root / "datasets" / "fire-smoke-voc" / "VOC2020"
    ann_dir = voc / "Annotations"
    img_dir = voc / "JPEGImages"
    if not ann_dir.is_dir():
        sys.exit(f"Annotations 目录不存在: {ann_dir}")

    xmls = sorted(ann_dir.glob("*.xml"))
    images = sorted(p for p in img_dir.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
    counts: Counter[str] = Counter()
    for xml in xmls:
        tree = ET.parse(xml)
        for obj in tree.getroot().findall("object"):
            name = (obj.findtext("name") or "").strip()
            if name:
                counts[name] += 1

    classes = sorted(counts)
    report = {
        "xml_count": len(xmls),
        "image_count": len(images),
        "class_counts": dict(counts),
        "classes": classes,
    }
    report_path = root / "datasets" / "reports" / "voc_stats.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if len(classes) == 1:
        print(f"[提示] 当前标注仅含 {classes[0]} 单类；烟类兜底策略见设计文档 8.2")


if __name__ == "__main__":
    main()
