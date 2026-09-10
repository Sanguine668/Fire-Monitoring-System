"""生成数据集预览相册：缩略图 + 点击查看原图，并统计标注信息。"""
from __future__ import annotations

import html
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[3]
VOC = ROOT / "datasets" / "fire-smoke-voc" / "VOC2020"
IMG_DIR = VOC / "JPEGImages"
ANN_DIR = VOC / "Annotations"
OUT_DIR = ROOT / "docs" / "课程任务" / "数据集预览"
THUMB_DIR = OUT_DIR / "thumbnails"


def label_stats() -> dict[str, int]:
    counts: dict[str, int] = {}
    for xml in ANN_DIR.glob("*.xml"):
        for obj in ET.parse(xml).getroot().findall("object"):
            name = (obj.findtext("name") or "").strip() or "unknown"
            counts[name] = counts.get(name, 0) + 1
    return counts


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    images = sorted(IMG_DIR.glob("*.jpg"))
    cards: list[str] = []
    for idx, path in enumerate(images, start=1):
        thumb = THUMB_DIR / f"{idx:05d}.jpg"
        if not thumb.exists():
            with Image.open(path) as im:
                im = ImageOps.exif_transpose(im).convert("RGB")
                im.thumbnail((240, 240))
                im.save(thumb, "JPEG", quality=72)
        rel_full = f"../../../datasets/fire-smoke-voc/VOC2020/JPEGImages/{path.name}"
        cards.append(
            f'<a class="card" href="{html.escape(rel_full)}" target="_blank" title="{html.escape(path.name)}">'
            f'<img loading="lazy" src="thumbnails/{thumb.name}" alt="{html.escape(path.name)}">'
            f"<span>{idx:05d}.jpg</span></a>"
        )
        if idx % 200 == 0:
            print(f"thumbs {idx}/{len(images)}")

    stats = label_stats()
    total_boxes = sum(stats.values())
    stats_html = "、".join(f"{k}: {v} 个框" for k, v in sorted(stats.items()))
    page = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>烟火数据集预览（gengyanlei VOC2020）</title>
<style>
  body {{ font-family: "Microsoft YaHei", sans-serif; margin: 24px 28px; background: #f6f7f9; color: #1f2937; }}
  h1 {{ font-size: 22px; margin: 0 0 6px; }}
  .meta {{ color: #4b5563; font-size: 14px; margin-bottom: 18px; line-height: 1.7; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 12px; }}
  .card {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 8px; text-align: center;
           text-decoration: none; color: #374151; font-size: 12px; box-shadow: 0 1px 2px rgba(0,0,0,.04); }}
  .card:hover {{ border-color: #1f4d78; box-shadow: 0 3px 10px rgba(31,77,120,.18); }}
  .card img {{ width: 100%; height: 170px; object-fit: cover; border-radius: 4px; display: block; margin-bottom: 6px; }}
</style>
</head>
<body>
  <h1>烟火检测训练集预览（gengyanlei VOC2020）</h1>
  <div class="meta">
    图片总数：<b>{len(images)}</b> 张　|　标注框总数：<b>{total_boxes}</b> 个　|　类别：{stats_html}<br>
    数据来源：gengyanlei/fire-smoke-detect-yolov4（Pascal VOC 格式，声明仅限学术探索）。
    点击任意图片可在新标签页查看原图；缩略图为自动生成，原图未改动。
  </div>
  <div class="grid">
    {''.join(cards)}
  </div>
</body>
</html>
"""
    index = OUT_DIR / "index.html"
    index.write_text(page, encoding="utf-8")
    (OUT_DIR / "stats.json").write_text(
        json.dumps({"images": len(images), "classes": stats}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(index)


if __name__ == "__main__":
    main()
