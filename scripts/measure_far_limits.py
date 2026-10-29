r"""远景识别极限实测：按尺度缩小模拟距离，测“最小可靠目标像素高度”并换算最远识别距离。

做法
----
1. 读远景图清单（默认 ``datasets/fire-smoke-v2/farfield.txt``）与 YOLO 格式 GT；
2. 对每个尺度把图片按 ``INTER_AREA`` 缩小、GT 同比缩小，仍按 ``imgsz=640`` 整图推理；
3. 预测框与 GT 按“同类 + IoU>=0.3”做一对一匹配，按缩放后 GT 框最短边像素分桶，
   统计每个桶的实例级召回（命中数 / 总数）；
4. 用“所有不短于 N px 的实例累计召回 >= 目标”定出最小可靠像素高度 N，
   再按小孔成像 ``D = f_px * H / h_px`` 换算最远可靠识别距离。

输出
----
* stdout：Markdown 表（图级召回、分桶实例召回、累计阈值、镜头距离表），可直接贴进文档；
* ``ai/runs/far-limits.json``：机器可读结果，含每个桶的实例数与命中数、逐像素直方图。

示例
----
    ai\.venv\Scripts\python.exe scripts\measure_far_limits.py
    ai\.venv\Scripts\python.exe scripts\measure_far_limits.py --limit 0 --scales 1.0
    ai\.venv\Scripts\python.exe scripts\measure_far_limits.py --limit 100 --tiled

两种缩放口径（重要，别用错）
--------------------------
`imgsz=640` 会把任意输入 letterbox 缩放到 640 宽。若只把图缩小、仍按 640 推理，目标在**网络输入里**
的像素数几乎不变（1280 宽的图直接缩到 0.5 与先缩到 0.5 再还原，网络里都是原尺寸的一半），
测到的只是重采样模糊，**不能**当距离用（脚本会打印实测证据）。所以默认用 `pad`：

* ``--mode pad``（默认）：缩小到 ``s`` 后**居中放回原画幅**（四周补灰），目标在画面里的相对尺寸真的变成
  ``s`` 倍，网络输入里的像素数随之变成 ``s`` 倍 —— 等价于“同一台相机、同一镜头，距离变成 1/s”；
  代价是视场变大、四周是合成填充，属于必要的近似（局限见 docs）。
* ``--mode resize``（题面字面口径）：缩小后直接送 640，会被 letterbox 归一化抵消，只反映模糊鲁棒性，
  保留它是为了复现/解释早期口径，**不要**拿它换算距离。

像素高度默认按 ``--ref-width``（1080p 的 1920）归一化：``h_ref = h_native × 1920 / 图像宽度``。
这样不同原生分辨率的图可以放在同一张表里，且 ``h_ref`` 与距离公式里的 1920 px 画幅一致；
对占多数的 1280×720 图，``h_ref = 1.5 × 原生像素``，而模型 640 输入里只占 ``h_ref / 3`` 像素。

口径
----
* “图级召回（有检出）”沿用 ``scripts/evaluate_v2.py`` 的口径：图上出现任意一类框即算命中，
  历史数字 81.2% / 94.0% / 96.0% 都是这个口径，便于交叉核对；
* “图级召回（命中GT）”更严格：至少有一个 GT 被同类且 IoU>=0.3 的框匹配；
* 类别 id 与 D-Fire 一致：0=smoke、1=fire，与 ``weights/fire26n-v2-best.pt`` 的 ``names`` 对齐；
* GT 约定：``<图片目录的上级>/labels/<文件名>.txt``，每行 ``cls xc yc w h``（归一化，YOLO 格式），
  可用 ``--labels-dir`` 覆盖；
* 尺度缩小只是距离的几何近似，不含大气扰动、雾霾、压缩失真，结论必须带上这个限制（见 docs）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.tiling import merge_detections, tile_frame  # noqa: E402

# 最短边分桶：左闭右开，最后一档为 40 px 以上
BUCKETS: tuple[tuple[float, float | None], ...] = (
    (0.0, 6.0),
    (6.0, 10.0),
    (10.0, 14.0),
    (14.0, 20.0),
    (20.0, 28.0),
    (28.0, 40.0),
    (40.0, None),
)
BUCKET_LABELS = ("0-6", "6-10", "10-14", "14-20", "20-28", "28-40", "40+")


# ---------------------------------------------------------------- 基础工具


def read_list(path: Path) -> list[Path]:
    """读图片清单：一行一个路径，相对路径按仓库根解析。"""
    files: list[Path] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        p = Path(line)
        files.append(p if p.is_absolute() else ROOT / p)
    return files


def read_bgr(path: Path) -> np.ndarray:
    """用 PIL 读图再转 BGR —— 仓库路径含中文，cv2.imread 在 Windows 上会失败。"""
    with Image.open(path) as im:
        return np.array(im.convert("RGB"))[:, :, ::-1].copy()


def label_path(image: Path, labels_dir: Path | None) -> Path:
    if labels_dir is not None:
        return labels_dir / f"{image.stem}.txt"
    # 与 scripts/eval_detector.py 一致：images/ 的隔壁就是 labels/
    return image.parent.parent / "labels" / f"{image.stem}.txt"


def load_gt(image: Path, width: int, height: int, labels_dir: Path | None) -> list[dict]:
    """读 YOLO 标签并转成像素坐标 GT 列表。"""
    lp = label_path(image, labels_dir)
    if not lp.is_file():
        raise SystemExit(
            f"缺少标签文件：{lp}\n"
            "约定为 <图片目录的上级>/labels/<文件名>.txt（YOLO 格式），可用 --labels-dir 指定。"
        )
    boxes: list[dict] = []
    for line in lp.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        cls = int(float(parts[0]))
        xc, yc, bw, bh = (float(v) for v in parts[1:5])
        x1 = max(0.0, (xc - bw / 2) * width)
        y1 = max(0.0, (yc - bh / 2) * height)
        x2 = min(float(width), (xc + bw / 2) * width)
        y2 = min(float(height), (yc + bh / 2) * height)
        if x2 - x1 <= 0 or y2 - y1 <= 0:
            continue
        boxes.append({"cls": cls, "x1": x1, "y1": y1, "x2": x2, "y2": y2})
    return boxes


def iou(a: dict, b: dict) -> float:
    ix1, iy1 = max(a["x1"], b["x1"]), max(a["y1"], b["y1"])
    ix2, iy2 = min(a["x2"], b["x2"]), min(a["y2"], b["y2"])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter <= 0:
        return 0.0
    area_a = (a["x2"] - a["x1"]) * (a["y2"] - a["y1"])
    area_b = (b["x2"] - b["x1"]) * (b["y2"] - b["y1"])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def match_pairs(preds: list[dict], gts: list[dict], iou_thr: float) -> tuple[set[int], set[int]]:
    """同类、IoU>=阈值的一对一匹配；返回（被命中的 GT 下标, 被命中的预测下标）。"""
    pairs: list[tuple[float, int, int]] = []
    for gi, g in enumerate(gts):
        for pi, p in enumerate(preds):
            if p["cls"] != g["cls"]:
                continue
            v = iou(g, p)
            if v >= iou_thr:
                pairs.append((v, gi, pi))
    pairs.sort(reverse=True)  # IoU 从高到低贪心，结果与遍历顺序无关
    used_p: set[int] = set()
    used_g: set[int] = set()
    for _v, gi, pi in pairs:
        if gi in used_g or pi in used_p:
            continue
        used_g.add(gi)
        used_p.add(pi)
    return used_g, used_p


def match_gts(preds: list[dict], gts: list[dict], iou_thr: float) -> set[int]:
    """同类、IoU>=阈值的一对一匹配；返回被命中的 GT 下标集合。"""
    return match_pairs(preds, gts, iou_thr)[0]


def bucket_index(short_px: float) -> int | None:
    for i, (lo, hi) in enumerate(BUCKETS):
        if short_px >= lo and (hi is None or short_px < hi):
            return i
    return None


def pct(value: float | None, digits: int = 1) -> str:
    return "–" if value is None else f"{value * 100:.{digits}f}%"


# ---------------------------------------------------------------- 推理


def _result_to_dets(res) -> list[dict]:
    """把 ultralytics 的单图结果转成按置信度降序的框（像素坐标）。"""
    if res.boxes is None:
        return []
    out: list[dict] = []
    for box, conf, ci in zip(
        res.boxes.xyxy.cpu().numpy(), res.boxes.conf.cpu().numpy(), res.boxes.cls.cpu().numpy()
    ):
        x1, y1, x2, y2 = (float(v) for v in box)
        out.append({"cls": int(ci), "conf": float(conf), "x1": x1, "y1": y1, "x2": x2, "y2": y2})
    out.sort(key=lambda d: -d["conf"])
    return out


def predict(model, frame: np.ndarray, args, conf: float | None = None) -> list[dict]:
    """整图推理，返回按置信度降序的框（像素坐标）。"""
    res = model.predict(
        frame, imgsz=args.imgsz, conf=args.conf if conf is None else conf,
        device=args.device, verbose=False,
    )[0]
    return _result_to_dets(res)


def predict_batch(model, frames: list[np.ndarray], args, conf: float | None = None) -> list[list[dict]]:
    """批量推理（一次前向处理多张切片，与生产端 detect_tiled 的批处理语义一致）。"""
    if not frames:
        return []
    res_list = model.predict(
        frames, imgsz=args.imgsz, conf=args.conf if conf is None else conf,
        device=args.device, verbose=False,
    )
    return [_result_to_dets(r) for r in res_list]


def predict_tiled(model, frame: np.ndarray, args, name_of: dict[int, str]) -> list[dict]:
    """切片推理：语义与 backend/app/detector.py 的 detect_tiled 一致（640 瓦片、0.2 重叠、跨片 NMS）。"""
    cls_of = {v: k for k, v in name_of.items()}
    merged: list[dict] = []
    for tile in tile_frame(frame, args.tile_size, args.overlap):
        for det in predict(model, tile.image, args):
            x, y = float(round(det["x1"])), float(round(det["y1"]))
            w, h = float(round(det["x2"] - det["x1"])), float(round(det["y2"] - det["y1"]))
            merged.append(
                {
                    "type": name_of[det["cls"]],
                    "confidence": det["conf"],
                    "bbox": [round(x + tile.x), round(y + tile.y), round(w), round(h)],
                }
            )
    kept = merge_detections(merged, 0.5)
    out = []
    for det in kept:
        x, y, w, h = det["bbox"]
        out.append(
            {
                "cls": cls_of[det["type"]],
                "conf": float(det["confidence"]),
                "x1": float(x),
                "y1": float(y),
                "x2": float(x + w),
                "y2": float(y + h),
            }
        )
    out.sort(key=lambda d: -d["conf"])
    return out


# ---------------------------------------------------------------- 多尺度切片消融
#
# 配置名承载全部推理语义：``whole-640``、``tiled-640``、``tiled-640+960``。
# 推理时先用 ``--cache-conf`` 的低阈值缓存全图坐标框，再对每个阈值“先过滤、后跨片/跨尺度
# NMS”，这与“以该阈值直接推理”等价（NMS 只可能被更高分框抑制），因此一次前向可评估整条
# 阈值曲线，避免重复推理。

CONFIG_RE = re.compile(r"^(whole|tiled)-(\d+(?:\+\d+)*)$")
CLASS_KEYS = (("smoke", 0), ("fire", 1))
CLASS_ID_OF = {"smoke": 0, "fire": 1}


def parse_configs(text: str) -> list[dict]:
    """把 ``whole-640,tiled-640+960`` 解析成配置列表。"""
    configs: list[dict] = []
    for raw in text.split(","):
        name = raw.strip()
        if not name:
            continue
        m = CONFIG_RE.match(name)
        if not m:
            raise SystemExit(f"无法解析配置 `{name}`，应形如 whole-640 或 tiled-640+960")
        kind = m.group(1)
        sizes = [int(v) for v in m.group(2).split("+")]
        configs.append({"name": name, "kind": kind, "tiles": sizes})
    if not configs:
        raise SystemExit("--configs 不能为空")
    return configs


def new_class_stat() -> dict:
    return {
        "images": 0,
        "images_with_gt": 0,
        "images_hit": 0,
        "instances": 0,
        "tp": 0,
        "pred_instances": 0,
        "images_with_pred": 0,
        "images_tp": 0,
    }


def new_any_stat() -> dict:
    return {"images": 0, "images_any": 0, "images_matched": 0, "images_with_pred": 0, "images_tp": 0}


def new_threshold_stat() -> dict:
    return {"smoke": new_class_stat(), "fire": new_class_stat(), "any": new_any_stat()}


def _ratio(num: float, den: float, digits: int = 4) -> float | None:
    return round(num / den, digits) if den else None


def finalize_class(st: dict) -> dict:
    out = dict(st)
    out["image_recall"] = _ratio(st["images_hit"], st["images_with_gt"])
    out["instance_recall"] = _ratio(st["tp"], st["instances"])
    out["instance_precision"] = _ratio(st["tp"], st["pred_instances"])
    out["image_precision"] = _ratio(st["images_tp"], st["images_with_pred"])
    out["fp_images"] = st["images_with_pred"] - st["images_tp"]
    out["fp_instances"] = st["pred_instances"] - st["tp"]
    out["fn_instances"] = st["instances"] - st["tp"]
    return out


def finalize_any(st: dict) -> dict:
    out = dict(st)
    out["image_recall_any"] = _ratio(st["images_any"], st["images"])
    out["image_recall_matched"] = _ratio(st["images_matched"], st["images"])
    out["image_precision"] = _ratio(st["images_tp"], st["images_with_pred"])
    return out


def finalize_threshold(st: dict) -> dict:
    return {
        "smoke": finalize_class(st["smoke"]),
        "fire": finalize_class(st["fire"]),
        "any": finalize_any(st["any"]),
    }


def _accumulate(stat: dict, gts: list[dict], preds: list[dict], iou_thr: float) -> None:
    """把一张图的 GT 与预测累计进统计（同类 + IoU 一对一匹配）。"""
    stat["any"]["images"] += 1
    stat["any"]["images_any"] += bool(preds)
    stat["any"]["images_with_pred"] += bool(preds)
    used_g_all, used_p_all = match_pairs(preds, gts, iou_thr)
    stat["any"]["images_matched"] += bool(used_g_all)
    stat["any"]["images_tp"] += bool(used_p_all)

    for key, cls_id in CLASS_KEYS:
        g = [x for x in gts if x["cls"] == cls_id]
        p = [x for x in preds if x["cls"] == cls_id]
        used_g, used_p = match_pairs(p, g, iou_thr)
        st = stat[key]
        st["images"] += 1
        st["images_with_gt"] += bool(g)
        st["images_hit"] += bool(used_g)
        st["instances"] += len(g)
        st["tp"] += len(used_g)
        st["pred_instances"] += len(p)
        st["images_with_pred"] += bool(p)
        st["images_tp"] += bool(used_p)


def collect_raw(model, frame: np.ndarray, spec: dict, args, name_of: dict[int, str]) -> list[dict]:
    """缓存一张图在低阈值下的全图坐标框。

    tiled 配置的平移/取整语义与 ``backend/app/detector.py::detect_tiled`` 完全一致；
    跨尺度合并留到阈值过滤之后再做（见 ``threshold_dets``）。
    """
    if spec["kind"] == "whole":
        return [
            {
                "type": name_of[d["cls"]],
                "confidence": d["conf"],
                "x1": d["x1"],
                "y1": d["y1"],
                "x2": d["x2"],
                "y2": d["y2"],
            }
            for d in predict(model, frame, args, args.cache_conf)
        ]

    tiles: list[tuple[int, object]] = []
    for size in spec["tiles"]:
        tiles.extend((size, t) for t in tile_frame(frame, size, args.overlap))
    dets = predict_batch(model, [t.image for _size, t in tiles], args, args.cache_conf)
    raw: list[dict] = []
    for (_size, tile), boxes in zip(tiles, dets):
        for d in boxes:
            x = round(d["x1"]) + tile.x
            y = round(d["y1"]) + tile.y
            w = round(d["x2"] - d["x1"])
            h = round(d["y2"] - d["y1"])
            raw.append(
                {
                    "type": name_of[d["cls"]],
                    "confidence": d["conf"],
                    "x1": float(x),
                    "y1": float(y),
                    "x2": float(x + w),
                    "y2": float(y + h),
                }
            )
    return raw


def threshold_dets(raw: list[dict], thr: float, merge_iou: float, tiled: bool) -> list[dict]:
    """按阈值过滤缓存框；tiled 配置在过滤后做跨片/跨尺度 NMS。"""
    kept = [d for d in raw if d["confidence"] >= thr]
    if not tiled:
        return [
            {"cls": CLASS_ID_OF[d["type"]], "conf": d["confidence"],
             "x1": d["x1"], "y1": d["y1"], "x2": d["x2"], "y2": d["y2"]}
            for d in kept
        ]
    items = [
        {
            "type": d["type"],
            "confidence": d["confidence"],
            "bbox": [
                int(round(d["x1"])),
                int(round(d["y1"])),
                int(round(d["x2"] - d["x1"])),
                int(round(d["y2"] - d["y1"])),
            ],
        }
        for d in kept
    ]
    merged = merge_detections(items, merge_iou)
    return [
        {
            "cls": CLASS_ID_OF[d["type"]],
            "conf": d["confidence"],
            "x1": float(d["bbox"][0]),
            "y1": float(d["bbox"][1]),
            "x2": float(d["bbox"][0] + d["bbox"][2]),
            "y2": float(d["bbox"][1] + d["bbox"][3]),
        }
        for d in merged
    ]


def evaluate_configs(files, model, configs: list[dict], args, name_of) -> tuple[dict, float]:
    """同一批图上跑所有配置；每张图只推理一次，阈值曲线在缓存上评估。"""
    thresholds = args.threshold_list
    primary = args.primary
    stats: dict[str, dict] = {
        cfg["name"]: {
            "full": {t: new_threshold_stat() for t in thresholds},
            "first150": {t: new_threshold_stat() for t in thresholds},
            "infer_s": 0.0,
            "merge_s": 0.0,
        }
        for cfg in configs
    }
    started = time.perf_counter()
    for i, f in enumerate(files, 1):
        img = read_bgr(f)
        height, width = img.shape[:2]
        gts = load_gt(f, width, height, Path(args.labels_dir) if args.labels_dir else None)
        for cfg in configs:
            st = stats[cfg["name"]]
            t0 = time.perf_counter()
            raw = collect_raw(model, img, cfg, args, name_of)
            st["infer_s"] += time.perf_counter() - t0
            for thr in thresholds:
                t1 = time.perf_counter()
                preds = threshold_dets(raw, thr, args.merge_iou, cfg["kind"] == "tiled")
                dt_merge = time.perf_counter() - t1
                if abs(thr - primary) < 1e-9:
                    st["merge_s"] += dt_merge
                _accumulate(st["full"][thr], gts, preds, args.iou)
                if args.tune_limit and i <= args.tune_limit:
                    _accumulate(st["first150"][thr], gts, preds, args.iou)
        if i % 50 == 0 or i == len(files):
            print(f"  已处理 {i}/{len(files)} 张", file=sys.stderr, flush=True)
    return stats, time.perf_counter() - started


def _ms_per_image(st: dict, key: str, n: int) -> float:
    return round(st[key] / n * 1000, 1) if n else 0.0


def _count_rate(num: int, den: int, digits: int = 1) -> str:
    return f"{num}/{den} ({pct(num / den if den else None, digits)})"


def config_rows(configs, stats, n_images: int, thr: float, scope: str) -> list[dict]:
    rows = []
    for cfg in configs:
        st = stats[cfg["name"]]
        block = st[scope][thr]
        smoke = finalize_class(block["smoke"])
        fire = finalize_class(block["fire"])
        any_st = finalize_any(block["any"])
        rows.append(
            {
                "config": cfg["name"],
                "kind": cfg["kind"],
                "tile_scales": cfg["tiles"],
                "smoke_image_hit": smoke["images_hit"],
                "smoke_image_total": smoke["images_with_gt"],
                "smoke_image_recall": smoke["image_recall"],
                "smoke_instance_matched": smoke["tp"],
                "smoke_instance_total": smoke["instances"],
                "smoke_instance_recall": smoke["instance_recall"],
                "smoke_instance_precision": smoke["instance_precision"],
                "smoke_image_precision": smoke["image_precision"],
                "smoke_fp_images": smoke["fp_images"],
                "smoke_fp_instances": smoke["fp_instances"],
                "fire_image_hit": fire["images_hit"],
                "fire_image_total": fire["images_with_gt"],
                "fire_image_recall": fire["image_recall"],
                "historical_images_any": any_st["images_any"],
                "historical_image_recall_any": any_st["image_recall_any"],
                "historical_images_matched": any_st["images_matched"],
                "historical_image_recall_matched": any_st["image_recall_matched"],
                "ms_per_image": round(st["infer_s"] / n_images * 1000, 1) if n_images else 0.0,
            }
        )
    return rows


def print_config_table(title: str, rows: list[dict], n_images: int) -> None:
    print(f"\n### {title}（{n_images} 张）\n")
    print(
        "| 配置 | 烟雾图级召回 | 烟雾实例召回 | 烟雾实例精确率 | 烟雾图级精确率 | "
        "烟雾FP图数 | 火焰图级召回 | 单帧推理 |"
    )
    print("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for r in rows:
        print(
            f"| `{r['config']}` | {_count_rate(r['smoke_image_hit'], r['smoke_image_total'])} | "
            f"{_count_rate(r['smoke_instance_matched'], r['smoke_instance_total'])} | "
            f"{pct(r['smoke_instance_precision'])} | "
            f"{pct(r['smoke_image_precision'])} | "
            f"{r['smoke_fp_images']} | {_count_rate(r['fire_image_hit'], r['fire_image_total'])} | "
            f"{r['ms_per_image']:.1f} ms |"
        )


def print_sweep_table(config: str, stats: dict, n_images: int, thresholds: list[float], scope: str) -> list[dict]:
    print(f"\n### 阈值扫描：`{config}`（{n_images} 张）\n")
    print(
        "| 烟雾 conf | 烟雾图级召回 | 烟雾实例召回 | 烟雾实例精确率 | 烟雾图级精确率 | "
        "烟雾FP图数 | 火焰图级召回 |"
    )
    print("| --- | --- | --- | --- | --- | --- | --- |")
    rows = []
    for thr in thresholds:
        block = stats[config][scope][thr]
        smoke = finalize_class(block["smoke"])
        fire = finalize_class(block["fire"])
        rows.append({"threshold": thr, "smoke": smoke, "fire": fire})
        print(
            f"| {thr:.2f} | {_count_rate(smoke['images_hit'], smoke['images_with_gt'])} | "
            f"{_count_rate(smoke['tp'], smoke['instances'])} | "
            f"{pct(smoke['instance_precision'])} | "
            f"{pct(smoke['image_precision'])} | "
            f"{smoke['fp_images']} | {_count_rate(fire['images_hit'], fire['images_with_gt'])} |"
        )
    return rows


# ---------------------------------------------------------------- 评测主循环


def new_stat() -> dict:
    return {
        "images": 0,
        "images_any": 0,
        "images_matched": 0,
        "instances": 0,
        "matched": 0,
        "seconds": 0.0,
        "buckets": {lbl: {"total": 0, "matched": 0} for lbl in BUCKET_LABELS},
        "hist": {},
    }


def build_frame(img: np.ndarray, s: float, mode: str, pad_value: int = 114):
    """按尺度构造送进模型的画幅。

    返回（frame, 缩放后宽, 缩放后高, 平移 dx, 平移 dy）；平移量用于把 GT 框挪到画幅坐标里。
    """
    height, width = img.shape[:2]
    nw, nh = max(1, round(width * s)), max(1, round(height * s))
    if (nw, nh) == (width, height):
        return img, nw, nh, 0, 0
    small = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
    if mode == "resize":
        # 字面口径：直接送 640，letterbox 会把目标放大回原尺寸
        return small, nw, nh, 0, 0
    # 物理正确口径：缩小后居中放回原画幅，目标的相对尺寸真的变小
    dx, dy = (width - nw) // 2, (height - nh) // 2
    canvas = np.full((height, width, 3), pad_value, dtype=np.uint8)
    canvas[dy : dy + nh, dx : dx + nw] = small
    return canvas, nw, nh, dx, dy


def evaluate(files: list[Path], model, scales: list[float], args, name_of, tiled: bool) -> dict:
    """在给定尺度上跑一遍评测，返回 {scale: stat}。"""
    stats = {s: new_stat() for s in scales}
    for i, f in enumerate(files, 1):
        img = read_bgr(f)
        height, width = img.shape[:2]
        gts = load_gt(f, width, height, Path(args.labels_dir) if args.labels_dir else None)
        for s in scales:
            frame, nw, nh, dx, dy = build_frame(img, s, args.mode, args.pad_value)
            t0 = time.perf_counter()
            preds = predict_tiled(model, frame, args, name_of) if tiled else predict(model, frame, args)
            dt = time.perf_counter() - t0

            sx, sy = nw / width, nh / height
            # 匹配必须在画幅坐标里做；归一化只用于“报出的像素高度”，与距离公式的 1080p 画幅对齐
            norm = args.ref_width / width
            scaled = [
                {
                    "cls": g["cls"],
                    "x1": g["x1"] * sx + dx,
                    "y1": g["y1"] * sy + dy,
                    "x2": g["x2"] * sx + dx,
                    "y2": g["y2"] * sy + dy,
                }
                for g in gts
            ]
            hit = match_gts(preds, scaled, args.iou)

            st = stats[s]
            st["images"] += 1
            st["seconds"] += dt
            if preds:
                st["images_any"] += 1
            if hit:
                st["images_matched"] += 1
            st["instances"] += len(scaled)
            st["matched"] += len(hit)
            for gi, g in enumerate(scaled):
                short = min(g["x2"] - g["x1"], g["y2"] - g["y1"]) * norm
                ok = 1 if gi in hit else 0
                bi = bucket_index(short)
                if bi is not None:
                    b = st["buckets"][BUCKET_LABELS[bi]]
                    b["total"] += 1
                    b["matched"] += ok
                key = int(short)  # 向下取整到 1 px 的直方图
                cell = st["hist"].setdefault(key, [0, 0])
                cell[0] += 1
                cell[1] += ok
        if i % 25 == 0 or i == len(files):
            print(f"  已处理 {i}/{len(files)} 张", file=sys.stderr, flush=True)
    return stats


# ---------------------------------------------------------------- 统计与换算


def merge_stats(stats: dict) -> tuple[dict, dict[int, list[int]]]:
    """合并各尺度：分桶统计 + 逐像素直方图。"""
    merged = {lbl: {"total": 0, "matched": 0} for lbl in BUCKET_LABELS}
    hist: dict[int, list[int]] = {}
    for st in stats.values():
        for lbl in BUCKET_LABELS:
            merged[lbl]["total"] += st["buckets"][lbl]["total"]
            merged[lbl]["matched"] += st["buckets"][lbl]["matched"]
        for key, (n, m) in st["hist"].items():
            cell = hist.setdefault(key, [0, 0])
            cell[0] += n
            cell[1] += m
    for m in merged.values():
        m["recall"] = m["matched"] / m["total"] if m["total"] else 0.0
    return merged, hist


def cumulative_curve(hist: dict[int, list[int]]) -> list[dict]:
    """R(t) = 所有最短边 >= t px 的实例召回；t 从 0 到最大像素逐点给出。"""
    max_px = max(hist) if hist else 0
    per_total = [0] * (max_px + 2)
    per_matched = [0] * (max_px + 2)
    for key, (n, m) in hist.items():
        per_total[key] += n
        per_matched[key] += m
    curve = []
    cum_t = cum_m = 0
    for t in range(max_px, -1, -1):
        cum_t += per_total[t]
        cum_m += per_matched[t]
        curve.append(
            {"px": t, "total": cum_t, "matched": cum_m, "recall": cum_m / cum_t if cum_t else 0.0}
        )
    curve.reverse()
    return curve


def first_px_at(curve: list[dict], target: float) -> dict | None:
    for row in curve:
        if row["px"] >= 1 and row["total"] and row["recall"] >= target:
            return row
    return None


def interpolate_px(curve: list[dict], target: float) -> float | None:
    """在步进的累计曲线上线性插值出首次达到目标的像素值。"""
    row = first_px_at(curve, target)
    if row is None:
        return None
    prev = curve[row["px"] - 1]
    if row["recall"] <= prev["recall"]:
        return float(row["px"])
    return (row["px"] - 1) + (target - prev["recall"]) / (row["recall"] - prev["recall"])


def local_curve(hist: dict[int, list[int]], width: int = 8) -> list[dict]:
    """局部召回：每个宽度为 width 的像素窗口内“命中/总数”，反映“刚好这么大的目标”有多难。"""
    if not hist:
        return []
    max_px = max(hist)
    per_total = [0] * (max_px + 1)
    per_matched = [0] * (max_px + 1)
    for key, (n, m) in hist.items():
        per_total[key] += n
        per_matched[key] += m
    rows = []
    for lo in range(0, max_px + 1, width):
        total = sum(per_total[lo : lo + width])
        matched = sum(per_matched[lo : lo + width])
        if total:
            rows.append(
                {
                    "lo": lo,
                    "hi": lo + width,
                    "total": total,
                    "matched": matched,
                    "recall": matched / total,
                }
            )
    return rows


def bucket_threshold(merged: dict, target: float) -> tuple[float, str] | tuple[None, None]:
    """分桶法：最小的、且其后所有非空桶都达到目标的桶下界。"""
    for i, lbl in enumerate(BUCKET_LABELS):
        cur = merged[lbl]
        if not cur["total"] or cur["recall"] < target:
            continue
        later = [merged[l] for l in BUCKET_LABELS[i + 1 :]]
        if all(m["recall"] >= target for m in later if m["total"]):
            return BUCKETS[i][0], lbl
    return None, None


def f_px(focal_mm: float, sensor_width_mm: float, image_width_px: int) -> float:
    return focal_mm / (sensor_width_mm / image_width_px)


def distance_km(focal_mm: float, sensor_width_mm: float, image_width_px: int,
                plume_m: float, target_px: float) -> float:
    return f_px(focal_mm, sensor_width_mm, image_width_px) * plume_m / target_px / 1000.0


# ---------------------------------------------------------------- 输出


def print_tables(files, scales, stats, merged, args, primary_px, bucket_label, curve, local) -> None:
    print("\n### 图级召回（按尺度）\n")
    print("| 尺度 | 图数 | 有检出（图级召回） | 命中GT（图级召回） | 实例命中/总数 | 实例召回 | 平均耗时 |")
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for s in scales:
        st = stats[s]
        n = st["images"]
        any_r = st["images_any"] / n if n else 0.0
        mt_r = st["images_matched"] / n if n else 0.0
        inst_r = st["matched"] / st["instances"] if st["instances"] else 0.0
        ms = st["seconds"] / n * 1000 if n else 0.0
        print(
            f"| {s:g} | {n} | {st['images_any']} ({pct(any_r)}) | {st['images_matched']} "
            f"({pct(mt_r)}) | {st['matched']}/{st['instances']} | {pct(inst_r)} | {ms:.1f} ms |"
        )

    print("\n### 分桶实例级召回（最短边 px；括号内为该桶实例数）\n")
    header = "| 最短边(px) | " + " | ".join(f"{s:g}×" for s in scales) + " |"
    print(header)
    print("| --- " * (len(scales) + 1) + "|")
    for lbl in BUCKET_LABELS:
        cells = []
        for s in scales:
            b = stats[s]["buckets"][lbl]
            cells.append(f"{pct(b['matched'] / b['total'] if b['total'] else None)} ({b['total']})")
        print(f"| {lbl} | " + " | ".join(cells) + " |")
    total_cells = []
    for s in scales:
        st = stats[s]
        total_cells.append(
            f"{pct(st['matched'] / st['instances'] if st['instances'] else None)} ({st['instances']})"
        )
    print("| 合计 | " + " | ".join(total_cells) + " |")

    print("\n### 各尺度合并后的分桶召回\n")
    print("| 最短边(px) | 实例数 | 命中 | 召回 |")
    print("| --- | --- | --- | --- |")
    for lbl in BUCKET_LABELS:
        m = merged[lbl]
        print(f"| {lbl} | {m['total']} | {m['matched']} | {pct(m['recall'])} |")

    print("\n## 最小可靠目标高度（1080p 等效画幅）\n")
    n_inst = sum(m["total"] for m in merged.values())
    n_hit = sum(m["matched"] for m in merged.values())
    if primary_px is None:
        print(f"- 未找到达到 {pct(args.target, 0)} 实例召回的像素阈值（样本量 {n_inst}）。")
        return
    cur = merged[bucket_label]
    idx = BUCKET_LABELS.index(bucket_label)
    print(f"- 判定口径（与分桶表一致）：最小的、且其后各桶都 ≥{pct(args.target, 0)} 的桶下界。")
    print(f"- **N = {primary_px:g} px** = 桶 `{bucket_label}` 的下界；该桶实例召回 "
          f"{pct(cur['recall'])}（{cur['matched']}/{cur['total']}）。")
    if idx > 0:
        prev_lbl = BUCKET_LABELS[idx - 1]
        prev = merged[prev_lbl]
        if prev["total"]:
            print(f"- 下一档 `{prev_lbl}` px：召回只有 {pct(prev['recall'])}"
                  f"（{prev['matched']}/{prev['total']}），是掉点最明显的一档。")
    near = [r for r in local if primary_px - 8 <= r["lo"] <= primary_px + 16]
    if near:
        print("- 局部滑窗交叉核对（每 " + str(args.local_window) + " px 一档）：" +
              "，".join(f"{r['lo']}-{r['hi']} px {pct(r['recall'])}({r['total']})" for r in near))
    print(f"- 累计口径（所有 ≥t 的实例，被大目标拉高、偏乐观）：" + "，".join(
        f"t={t}: {pct(curve[t]['recall'])}" for t in (24, 28, 32, 36, 40) if t < len(curve)
    ))
    print(f"- 合并样本：{len(files)} 张图、{n_inst} 个 GT 实例、命中 {n_hit} 个。")


def print_distance(args, px: float | None) -> dict:
    sensors = args.sensor_width_mm
    image_w = args.ref_width
    focal_list = [float(v) for v in args.lenses.split(",") if v.strip()]
    plume_list = [float(v) for v in args.plumes.split(",") if v.strip()]
    result: dict[str, dict[str, float]] = {}
    if px is None:
        return result

    print(f"\n## 几何换算（参考画幅 {image_w} px、{sensors} mm 靶面、阈值 {px:g} px）\n")
    print(f"- `f_px = f_mm / (sensor_width_mm / image_width_px)`，image_width_px = {image_w}（1080p）")
    print(f"- `D = f_px × H / h_px`，H 为烟羽高度，h_px 为最小可靠像素高度（{px:g} px）")
    print(f"- 模型输入 640 宽时，{px:g} px 只占网络输入里的 {px * 640 / image_w:.1f} px，这是真正的瓶颈")
    print(f"- 主镜头 {args.focal_mm:g} mm：`f_px = {f_px(args.focal_mm, sensors, image_w):.1f} px`，"
          f"{args.plume_m:g} m 烟羽 → "
          f"**{distance_km(args.focal_mm, sensors, image_w, args.plume_m, px):.1f} km**")
    print()
    print("| 镜头 | f_px | " + " | ".join(f"烟羽 {p:g} m" for p in plume_list) + " |")
    print("| --- | --- | " + " | ".join("---" for _ in plume_list) + " |")
    for focal in focal_list:
        row = []
        result[f"{focal:g}"] = {}
        for plume in plume_list:
            d = distance_km(focal, sensors, image_w, plume, px)
            row.append(f"{d:.1f} km")
            result[f"{focal:g}"][f"{plume:g}"] = round(d, 2)
        print(f"| {focal:g} mm | {f_px(focal, sensors, image_w):.0f} | " + " | ".join(row) + " |")
    return result


def print_tiled_compare(scales, stats, tiled_stats, args) -> dict:
    print("\n### 整图 vs 切片（同尺度）\n")
    print("| 尺度 | 图级召回 整图 | 图级召回 切片 | 实例召回 整图 | 实例召回 切片 | 耗时 整图/切片 |")
    print("| --- | --- | --- | --- | --- | --- |")
    out: dict[str, dict] = {}
    for s in scales:
        a, b = stats[s], tiled_stats[s]
        a_any = a["images_any"] / a["images"] if a["images"] else 0.0
        b_any = b["images_any"] / b["images"] if b["images"] else 0.0
        a_inst = a["matched"] / a["instances"] if a["instances"] else 0.0
        b_inst = b["matched"] / b["instances"] if b["instances"] else 0.0
        a_ms = a["seconds"] / a["images"] * 1000 if a["images"] else 0.0
        b_ms = b["seconds"] / b["images"] * 1000 if b["images"] else 0.0
        print(
            f"| {s:g} | {pct(a_any)} | {pct(b_any)} | {pct(a_inst)} | {pct(b_inst)} | "
            f"{a_ms:.1f} / {b_ms:.1f} ms |"
        )
        out[f"{s:g}"] = {
            "image_recall_plain": round(a_any, 4),
            "image_recall_tiled": round(b_any, 4),
            "instance_recall_plain": round(a_inst, 4),
            "instance_recall_tiled": round(b_inst, 4),
            "ms_plain": round(a_ms, 1),
            "ms_tiled": round(b_ms, 1),
        }
    return out


def stat_to_json(st: dict) -> dict:
    n = st["images"]
    inst = st["instances"]
    return {
        "images": n,
        "images_any": st["images_any"],
        "image_recall_any": round(st["images_any"] / n, 4) if n else 0.0,
        "images_matched": st["images_matched"],
        "image_recall_matched": round(st["images_matched"] / n, 4) if n else 0.0,
        "instances": inst,
        "matched": st["matched"],
        "instance_recall": round(st["matched"] / inst, 4) if inst else 0.0,
        "ms_per_image": round(st["seconds"] / n * 1000, 1) if n else 0.0,
        "buckets": {
            lbl: {
                "total": b["total"],
                "matched": b["matched"],
                "recall": round(b["matched"] / b["total"], 4) if b["total"] else 0.0,
            }
            for lbl, b in st["buckets"].items()
        },
    }


def _precision_ok(smoke: dict, baseline: dict, tol: float) -> bool:
    """实例级与图级精确率都不比基线低超过 tol（绝对百分点）。"""
    checks = []
    for key in ("instance_precision", "image_precision"):
        base_v, cur_v = baseline.get(key), smoke.get(key)
        if base_v is None or cur_v is None:
            continue
        checks.append(cur_v >= base_v - tol)
    return all(checks)


def _candidate(stats: dict, cfg_name: str, thr: float) -> dict:
    block = stats[cfg_name]["full"][thr]
    return {
        "config": cfg_name,
        "threshold": thr,
        "smoke": finalize_class(block["smoke"]),
        "fire": finalize_class(block["fire"]),
        "any": finalize_any(block["any"]),
    }


def _candidate_json(cand: dict) -> dict:
    smoke, fire = cand["smoke"], cand["fire"]
    return {
        "config": cand["config"],
        "threshold": cand["threshold"],
        "smoke_image_hit": smoke["images_hit"],
        "smoke_image_total": smoke["images_with_gt"],
        "smoke_image_recall": smoke["image_recall"],
        "smoke_instance_matched": smoke["tp"],
        "smoke_instance_total": smoke["instances"],
        "smoke_instance_recall": smoke["instance_recall"],
        "smoke_instance_precision": smoke["instance_precision"],
        "smoke_image_precision": smoke["image_precision"],
        "smoke_fp_images": smoke["fp_images"],
        "smoke_fp_instances": smoke["fp_instances"],
        "fire_image_hit": fire["images_hit"],
        "fire_image_total": fire["images_with_gt"],
        "fire_image_recall": fire["image_recall"],
        "historical_images_any": cand["any"]["images_any"],
        "historical_image_recall_any": cand["any"]["image_recall_any"],
    }


def run_config_mode(files, model, name_of, args, device_label: str) -> None:
    configs = parse_configs(args.configs)
    thresholds = args.threshold_list
    primary = args.primary
    n = len(files)
    tune_n = min(args.tune_limit, n) if args.tune_limit else 0

    print("# 远景烟雾召回提升实测（多尺度切片消融）\n")
    print(f"- 权重：`{args.weights}`（names={name_of}）")
    print(f"- 清单：`{args.list}`，{n} 张（调参子集：前 {tune_n} 张）")
    print(f"- 推理：imgsz={args.imgsz}，device={device_label}，切片重叠 {args.overlap:g}，"
          f"跨片 NMS IoU≥{args.merge_iou:g}")
    print(f"- 缓存推理阈值：conf≥{args.cache_conf:g}（阈值曲线在其上评估，等价于按各阈值直接推理）")
    print(f"- 匹配：同类 + IoU≥{args.iou}，一对一贪心；主表阈值 conf={primary:g}")
    print(f"- 配置：{', '.join(c['name'] for c in configs)}")
    print(f"- 目标：图级烟雾召回 ≥{pct(args.goal, 0)}")

    model.predict(
        np.zeros((640, 640, 3), dtype=np.uint8),
        imgsz=args.imgsz, conf=args.cache_conf, device=args.device, verbose=False,
    )  # 预热，避免第一张图的耗时污染统计

    stats, elapsed = evaluate_configs(files, model, configs, args, name_of)
    print(f"\n- 总耗时：{elapsed:.1f} s（{elapsed / n * 1000:.0f} ms/图，含 {len(configs)} 个配置 × "
          f"{len(thresholds)} 个阈值）")

    rows_full = config_rows(configs, stats, n, primary, "full")
    rows_tune = config_rows(configs, stats, tune_n, primary, "first150") if tune_n else []
    print_config_table(f"全量 {n} 张：配置消融（conf 主阈值）", rows_full, n)
    if rows_tune:
        print_config_table(f"调参子集：前 {tune_n} 张（同口径）", rows_tune, tune_n)

    baseline_row = next((r for r in rows_full if r["config"] == "whole-640"), rows_full[0])
    baseline_name = baseline_row["config"]
    baseline_smoke = finalize_class(stats[baseline_name]["full"][primary]["smoke"])
    print(
        f"\n- 基线 `{baseline_name}` @{primary:g}：烟雾图级 {_count_rate(baseline_row['smoke_image_hit'], baseline_row['smoke_image_total'])}"
        f"，烟雾实例 {_count_rate(baseline_row['smoke_instance_matched'], baseline_row['smoke_instance_total'])}"
        f"，实例精确率 {pct(baseline_row['smoke_instance_precision'])}"
        f"，图级精确率 {pct(baseline_row['smoke_image_precision'])}"
        f"，FP 图 {baseline_row['smoke_fp_images']}"
    )
    print(
        f"- 历史口径核对：`{baseline_name}` @{primary:g} 的“有检出”图级召回 = "
        f"{_count_rate(baseline_row['historical_images_any'], n)}（历史参考 422/520 = 81.2%），"
        f"命中 GT = {_count_rate(baseline_row['historical_images_matched'], n)}"
    )

    best_row = max(
        rows_full,
        key=lambda r: (
            r["smoke_image_recall"] or 0,
            r["smoke_instance_precision"] or 0,
            r["smoke_instance_recall"] or 0,
        ),
    )
    best = best_row["config"]
    print(f"\n- 按 conf={primary:g} 的图级烟雾召回选出最佳配置：`{best}`"
          f"（{_count_rate(best_row['smoke_image_hit'], best_row['smoke_image_total'])}）")

    sweep_rows = print_sweep_table(best, stats, n, thresholds, "full")

    sweep_cands = [_candidate(stats, best, thr) for thr in thresholds]
    goal_cands = [
        c for c in sweep_cands
        if (c["smoke"]["image_recall"] or 0) >= args.goal
        and _precision_ok(c["smoke"], baseline_smoke, args.precision_tolerance)
    ]
    if goal_cands:
        winner_cand = max(goal_cands, key=lambda c: (c["threshold"], c["smoke"]["instance_precision"] or 0))
    else:
        # 没达到目标时如实报告“召回最高”的组合，并在输出里标注精确率代价
        winner_cand = max(
            sweep_cands,
            key=lambda c: (c["smoke"]["image_recall"] or 0, c["smoke"]["instance_precision"] or 0),
        )

    win = winner_cand
    win_smoke = win["smoke"]
    target_met = (win_smoke["image_recall"] or 0) >= args.goal
    precision_ok = _precision_ok(win_smoke, baseline_smoke, args.precision_tolerance)
    print(
        f"\n- 胜出组合：`{win['config']}` @ conf={win['threshold']:.2f} → 图级烟雾召回 "
        f"{_count_rate(win_smoke['images_hit'], win_smoke['images_with_gt'])}"
        f"，实例召回 {_count_rate(win_smoke['tp'], win_smoke['instances'])}"
        f"，实例精确率 {pct(win_smoke['instance_precision'])}"
        f"（基线 {pct(baseline_smoke['instance_precision'])}）"
        f"，图级精确率 {pct(win_smoke['image_precision'])}"
        f"（基线 {pct(baseline_smoke['image_precision'])}）"
        f"，烟雾 FP 图 {win_smoke['fp_images']}"
    )
    print(f"- 目标 ≥{pct(args.goal, 0)}：{'达到' if target_met else '未达到'}；"
          f"精确率不劣于基线 {args.precision_tolerance * 100:.0f}pp：{'是' if precision_ok else '否'}")

    # 透明起见：所有配置 × 阈值里达到目标的组合都列出来
    all_pairs = [
        _candidate(stats, cfg["name"], thr) for cfg in configs for thr in thresholds
    ]
    all_goal = [c for c in all_pairs if (c["smoke"]["image_recall"] or 0) >= args.goal]
    if all_goal:
        print(f"- 全配置扫描中达到 ≥{pct(args.goal, 0)} 的组合共 {len(all_goal)} 个：")
        for c in sorted(all_goal, key=lambda c: (c["smoke"]["image_recall"] or 0), reverse=True)[:8]:
            print(
                f"  - `{c['config']}` @{c['threshold']:.2f}："
                f"{_count_rate(c['smoke']['images_hit'], c['smoke']['images_with_gt'])}"
                f"，实例精确率 {pct(c['smoke']['instance_precision'])}，FP 图 {c['smoke']['fp_images']}"
            )
    else:
        print(f"- 全配置扫描中没有任何组合达到 ≥{pct(args.goal, 0)}。")

    precise_pairs = [
        c for c in all_pairs if _precision_ok(c["smoke"], baseline_smoke, args.precision_tolerance)
    ]
    best_precise = (
        max(precise_pairs, key=lambda c: (c["smoke"]["image_recall"] or 0, c["threshold"]))
        if precise_pairs
        else None
    )
    if best_precise is not None:
        print(
            f"- 精确率约束下（实例级/图级都不比基线 {baseline_name}@{primary:g} 低超过 "
            f"{args.precision_tolerance * 100:.0f}pp）的最高召回：`{best_precise['config']}` "
            f"@{best_precise['threshold']:.2f} → "
            f"{_count_rate(best_precise['smoke']['images_hit'], best_precise['smoke']['images_with_gt'])}，"
            f"实例精确率 {pct(best_precise['smoke']['instance_precision'])}，"
            f"图级精确率 {pct(best_precise['smoke']['image_precision'])}"
        )
    else:
        print(f"- 没有任何配置在 {args.precision_tolerance * 100:.0f}pp 精确率容差内。")

    print("\n### 单帧推理成本\n")
    print("| 配置 | 单帧推理 | 相对整图 | 单帧合并 |")
    print("| --- | --- | --- | --- |")
    base_ms = next(r["ms_per_image"] for r in rows_full if r["config"] == baseline_name) or 1.0
    timing_json = {}
    for r in rows_full:
        st = stats[r["config"]]
        infer_ms = round(st["infer_s"] / n * 1000, 1) if n else 0.0
        merge_ms = round(st["merge_s"] / n * 1000, 2) if n else 0.0
        timing_json[r["config"]] = {
            "infer_ms_per_image": infer_ms,
            "merge_ms_per_image": merge_ms,
            "total_s": round(st["infer_s"] + st["merge_s"], 1),
            "speed_vs_whole": round(infer_ms / base_ms, 2) if base_ms else None,
        }
        print(f"| `{r['config']}` | {infer_ms:.1f} ms | {infer_ms / base_ms:.2f}× | {merge_ms:.2f} ms |")

    out_path = Path(args.out) if Path(args.out).is_absolute() else ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": {
            "mode": "config-ablation",
            "weights": args.weights,
            "list": args.list,
            "images": n,
            "tune_limit": tune_n,
            "configs": [c["name"] for c in configs],
            "tile_scales": {c["name"]: c["tiles"] for c in configs},
            "thresholds": thresholds,
            "primary_threshold": primary,
            "cache_conf": args.cache_conf,
            "merge_iou": args.merge_iou,
            "overlap": args.overlap,
            "iou": args.iou,
            "imgsz": args.imgsz,
            "device": device_label,
            "goal": args.goal,
            "precision_tolerance": args.precision_tolerance,
            "elapsed_s": round(elapsed, 1),
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        },
        "configs": {
            cfg["name"]: {
                "kind": cfg["kind"],
                "tile_scales": cfg["tiles"],
                "timing": timing_json[cfg["name"]],
                "full": {
                    f"{thr:g}": finalize_threshold(stats[cfg["name"]]["full"][thr])
                    for thr in thresholds
                },
                "first150": {
                    f"{thr:g}": finalize_threshold(stats[cfg["name"]]["first150"][thr])
                    for thr in thresholds
                }
                if tune_n
                else {},
            }
            for cfg in configs
        },
        "ablation": {
            "threshold": primary,
            "full": rows_full,
            "first150": rows_tune,
        },
        "sweep": {
            "config": best,
            "full": sweep_rows,
        },
        "winner": {
            **_candidate_json(win),
            "target_met": bool(target_met),
            "precision_ok": bool(precision_ok),
            "baseline": {
                "config": baseline_name,
                "threshold": primary,
                "smoke_image_recall": baseline_row["smoke_image_recall"],
                "smoke_instance_recall": baseline_row["smoke_instance_recall"],
                "smoke_instance_precision": baseline_row["smoke_instance_precision"],
                "smoke_image_precision": baseline_row["smoke_image_precision"],
            },
        },
        "goal_reached_combinations": [_candidate_json(c) for c in all_goal],
        "precision_constrained": _candidate_json(best_precise) if best_precise is not None else None,
        "cross_check": {
            "reference": {"whole640_conf025_images_any_520": 422,
                          "whole640_conf025_image_recall_any_520": 0.812},
            "measured": {
                "config": baseline_name,
                "threshold": primary,
                "images_any": baseline_row["historical_images_any"],
                "image_recall_any": baseline_row["historical_image_recall_any"],
            },
        },
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nJSON 已写入 `{out_path.relative_to(ROOT)}`。")


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # 表里有 ≥ / ≈ 等字符，避免 GBK 控制台报错
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(
        description="远景识别极限实测：尺度缩小模拟距离 → 召回-像素曲线 → 最小可靠像素高度",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--weights", default="weights/fire26n-v2-best.pt", help="模型权重")
    ap.add_argument("--list", default="datasets/fire-smoke-v2/farfield.txt", help="图片清单，每行一个路径")
    ap.add_argument("--labels-dir", default=None, help="GT 标签目录；默认 <图片目录的上级>/labels")
    ap.add_argument("--limit", type=int, default=150, help="只取清单前 N 张；0 表示全量")
    ap.add_argument("--scales", default="1.0,0.75,0.5,0.375,0.25,0.1875,0.125",
                    help="缩小系数，逗号分隔")
    ap.add_argument("--conf", type=float, default=0.25, help="推理置信度阈值")
    ap.add_argument("--iou", type=float, default=0.3, help="GT 与预测框匹配的 IoU 下限")
    ap.add_argument("--imgsz", type=int, default=640, help="推理输入尺寸")
    ap.add_argument("--device", default=None, help="推理设备，如 0 / cpu；默认自动")
    ap.add_argument("--tiled", action="store_true", help="对实例召回最好的两个尺度再做一遍切片推理")
    ap.add_argument("--tile-size", type=int, default=640, help="切片边长")
    ap.add_argument("--overlap", type=float, default=0.2, help="切片重叠率")
    ap.add_argument("--target", type=float, default=0.8, help="“可靠”的实例召回目标")
    ap.add_argument("--focal-mm", type=float, default=12.0, help="主镜头焦距（mm）")
    ap.add_argument("--lenses", default="4,8,12,25,50", help="距离表用的焦距列表（mm）")
    ap.add_argument("--mode", choices=("pad", "resize"), default="pad",
                    help="pad=缩小后居中放回原画幅（物理正确）；resize=缩小后直接送 640（题面字面口径，"
                         "会被 letterbox 归一化抵消，不用于换算距离）")
    ap.add_argument("--pad-value", type=int, default=114, help="pad 模式的填充灰度")
    ap.add_argument("--ref-width", type=int, default=1920,
                    help="像素高度归一化的参考画幅宽度，同时用作 f_px 的画幅（1080p=1920）")
    ap.add_argument("--sensor-width-mm", type=float, default=5.6,
                    help="传感器靶面宽度（1/2.8 英寸 ≈ 5.6 mm）")
    ap.add_argument("--plume-m", type=float, default=20.0, help="主假设的烟羽高度（m）")
    ap.add_argument("--plumes", default="10,20,30", help="距离表用的烟羽高度列表（m）")
    ap.add_argument("--out", default="ai/runs/far-limits.json", help="JSON 输出路径")
    ap.add_argument("--configs", default=None,
                    help="多尺度切片消融配置，逗号分隔（如 whole-640,tiled-640,tiled-640+960）；"
                         "给定时进入配置消融模式，不再执行 --scales 的缩小语义")
    ap.add_argument("--thresholds", default="0.45,0.30,0.25,0.20",
                    help="置信度阈值扫描列表（配置消融模式）")
    ap.add_argument("--primary", type=float, default=0.25,
                    help="配置消融主表使用的置信度阈值")
    ap.add_argument("--cache-conf", type=float, default=0.05,
                    help="缓存推理框所用低阈值（阈值曲线在其上评估）")
    ap.add_argument("--merge-iou", type=float, default=0.5,
                    help="跨片/跨尺度 NMS 的 IoU 阈值，与 detect_tiled 一致")
    ap.add_argument("--tune-limit", type=int, default=150,
                    help="调参子集大小（前 N 张，0 表示不做子集统计）")
    ap.add_argument("--goal", type=float, default=0.90, help="目标图级烟雾召回")
    ap.add_argument("--precision-tolerance", type=float, default=0.05,
                    help="相对基线的精确率容差（绝对百分点）")
    ap.add_argument("--local-window", type=int, default=8, help="分桶表的局部滑窗宽度（px）")
    args = ap.parse_args()

    scales = [float(v) for v in args.scales.split(",") if v.strip()]
    if not scales:
        raise SystemExit("--scales 不能为空")
    if args.ref_width <= 0:
        raise SystemExit("--ref-width 必须为正数")
    list_path = Path(args.list) if Path(args.list).is_absolute() else ROOT / args.list
    files = read_list(list_path)
    if args.limit:
        files = files[: args.limit]
    if not files:
        raise SystemExit(f"清单为空：{list_path}")

    model = YOLO(str(ROOT / args.weights) if not Path(args.weights).is_absolute() else args.weights)
    name_of = {int(k): str(v).lower() for k, v in model.names.items()}
    if set(name_of.values()) != {"smoke", "fire"}:
        raise SystemExit(f"模型类别应为 smoke/fire，实际为 {name_of}")

    device_label = str(args.device) if args.device not in (None, "") else "auto"
    if args.device in (None, ""):
        try:
            import torch

            device_label = "cuda:0" if torch.cuda.is_available() else "cpu"
        except Exception:  # noqa: BLE001 - 只是打印用
            pass

    args.threshold_list = sorted(
        {float(v) for v in args.thresholds.split(",") if v.strip()}, reverse=True
    )
    if not args.threshold_list:
        raise SystemExit("--thresholds 不能为空")
    if not any(abs(t - args.primary) < 1e-9 for t in args.threshold_list):
        args.threshold_list.append(args.primary)
    args.threshold_list.sort(reverse=True)

    if args.configs:
        run_config_mode(files, model, name_of, args, device_label)
        return

    print("# 远景识别极限实测\n")
    print(f"- 权重：`{args.weights}`（names={name_of}）")
    print(f"- 清单：`{args.list}`，取前 {len(files)} 张")
    print(f"- 推理：imgsz={args.imgsz}，conf={args.conf}，device={device_label}")
    print(f"- 缩放模式：`{args.mode}`" + (
        "（缩小后居中放回原画幅，目标在画面里的相对尺寸真的变小）" if args.mode == "pad"
        else "（⚠ 缩小后直接送 640，letterbox 会把目标放大回去，只反映模糊鲁棒性，不能换算距离）"
    ))
    print(f"- 像素归一化：参考画幅 {args.ref_width} px")
    print(f"- 匹配：同类 + IoU≥{args.iou}，一对一贪心")
    print(f"- 尺度：{', '.join(f'{s:g}' for s in scales)}")
    print(f"- 样本：{len(files)} 张图")

    started = time.perf_counter()
    model.predict(
        np.zeros((640, 640, 3), dtype=np.uint8),
        imgsz=args.imgsz, conf=args.conf, device=args.device, verbose=False,
    )  # 预热，避免第一张图的耗时污染统计
    stats = evaluate(files, model, scales, args, name_of, tiled=False)
    elapsed = time.perf_counter() - started

    merged, hist = merge_stats(stats)
    curve = cumulative_curve(hist)
    target_row = first_px_at(curve, args.target)
    interp = interpolate_px(curve, args.target)
    bucket_px, bucket_label = bucket_threshold(merged, args.target)

    print(f"- 耗时：{elapsed:.1f} s（{elapsed / len(files) * 1000:.0f} ms/图，含 {len(scales)} 个尺度）")

    local = local_curve(hist, args.local_window)
    print_tables(files, scales, stats, merged, args, target_row, bucket_label, curve, local)
    if target_row is not None:
        containing = bucket_label if bucket_label else None
        contain = merged.get(containing, {}) if containing else {}
        if contain:
            print(f"- 含该尺寸的桶：{containing} px，桶内召回 {pct(contain['recall'])}"
                  f"（{contain['matched']}/{contain['total']}）。")
        if bucket_px is not None and abs(bucket_px - target_row["px"]) > 0.01:
            print(f"- 分桶法（最小且其后各桶都 ≥{pct(args.target, 0)} 的桶下界）：{bucket_px:g} px，"
                  f"与逐像素累计法相差 {abs(bucket_px - target_row['px']):.0f} px。")
        if interp is not None:
            print(f"- 线性插值：≈ {interp:.1f} px。")
        for level in (0.75, 0.85):
            row = first_px_at(curve, level)
            if row is not None:
                print(f"- 若要求召回 ≥{pct(level, 0)}：N = {row['px']} px"
                      f"（{row['matched']}/{row['total']} = {pct(row['recall'])}）。")
        near = [r for r in curve if abs(r["px"] - target_row["px"]) <= 3]
        if near:
            print(f"- 阈值邻域（±3 px）样本量：" +
                  ", ".join(f"{r['px']}px:{r['total']}个" for r in near))

    distance = print_distance(args, target_row)

    tiled_result: dict = {}
    if args.tiled and len(scales) >= 1:
        ranked = sorted(
            scales,
            key=lambda s: (
                stats[s]["matched"] / stats[s]["instances"] if stats[s]["instances"] else 0.0,
                stats[s]["images_any"] / stats[s]["images"] if stats[s]["images"] else 0.0,
            ),
            reverse=True,
        )[:2]
        ranked.sort()
        print(f"\n切片推理尺度（实例召回最好的两个）：{', '.join(f'{s:g}' for s in ranked)}")
        tiled_stats = evaluate(files, model, ranked, args, name_of, tiled=True)
        tiled_result = {
            "scales": [f"{s:g}" for s in ranked],
            "per_scale": {f"{s:g}": stat_to_json(tiled_stats[s]) for s in ranked},
            "compare": print_tiled_compare(ranked, stats, tiled_stats, args),
        }

    out_path = Path(args.out) if Path(args.out).is_absolute() else ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": {
            "weights": args.weights,
            "list": args.list,
            "images": len(files),
            "scales": [f"{s:g}" for s in scales],
            "conf": args.conf,
            "iou": args.iou,
            "imgsz": args.imgsz,
            "device": device_label,
            "mode": args.mode,
            "ref_width": args.ref_width,
            "target_recall": args.target,
            "tiled": bool(args.tiled),
            "elapsed_s": round(elapsed, 1),
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        },
        "per_scale": {f"{s:g}": stat_to_json(stats[s]) for s in scales},
        "merged_buckets": {
            lbl: {
                "total": m["total"],
                "matched": m["matched"],
                "recall": round(m["recall"], 4),
            }
            for lbl, m in merged.items()
        },
        "threshold": {
            "criterion": f"instance recall >= {args.target}",
            "px": target_row["px"] if target_row else None,
            "px_interp": round(interp, 2) if interp is not None else None,
            "bucket": bucket_label,
            "bucket_lower_px": bucket_px,
            "total_instances": target_row["total"] if target_row else None,
            "matched_instances": target_row["matched"] if target_row else None,
            "recall_at_px": round(target_row["recall"], 4) if target_row else None,
            "px_at_recall": {
                f"{lv:g}": (first_px_at(curve, lv) or {}).get("px")
                for lv in (0.75, 0.8, 0.85, 0.9)
            },
        },
        "distance_km": distance,
        "histogram": curve,
    }
    if tiled_result:
        payload["tiled"] = tiled_result
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nJSON 已写入 `{out_path.relative_to(ROOT)}`。")


if __name__ == "__main__":
    main()
