# 远距离识别与烟类检测能力升级 · 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让系统同时具备烟类检测与远距离小目标识别能力，并留下可量化对比的证据。

**Architecture:** 分两条互不阻塞的线：① 数据线——把 D-Fire（21,527 张、fire+smoke、44.6% 小目标）整理成训练集并重训出双类模型；② 推理线——在检测链路中加入"按需切片"推理，不改模型、只改推理方式，因此可与训练并行推进。两条线在最后的评估环节汇合：同一模型下对比整图与切片的远景召回。

**Tech Stack:** Python 3.12 / Ultralytics（`ai/.venv`，torch 2.11+cu128）/ FastAPI / Vue3；显卡 RTX 4050 Laptop 6GB。

## Global Constraints

- 所有 Python 命令必须用 `ai\.venv\Scripts\python`，不要用系统 Python（系统环境没装 torch/ultralytics）。
- 训练与推理必须走 GPU：命令前设 `$env:FIREGUARD_DEVICE='0'`；CPU 模式在本机会因线程与内存限制报错。
- **类别编号固定为 0 = smoke、1 = fire**（已交叉验证：D-Fire 官方 fire 14,692 框对应类别 1、smoke 11,865 框对应类别 0）。任何地方不得颠倒。
- 数据集与模型权重不入 Git（`datasets/`、`*.pt` 已在 `.gitignore` 中）。
- 路径含中文，**禁止用 `cv2.imread` / `cv2.imwrite` 读写本地图片**（Windows 下读不了非 ASCII 路径）；改用 `PIL.Image` 或 `cv2.imdecode(np.fromfile(path, np.uint8), ...)`。
- 提交信息格式：`类型(范围): 说明 - 姓名`。

## 文件结构

| 文件 | 职责 | 状态 |
| --- | --- | --- |
| `scripts/prepare_dfire.py` | 数据管线：过滤退化框、生成 train/val/test 列表与 data.yaml、导出小目标评估子集 | 新建 |
| `datasets/fire-smoke-v2/` | 数据集描述文件（只放 data.yaml 与四个 txt 列表，不复制图片） | 新建 |
| `scripts/check_dataset.py` | 用 ultralytics 自带函数验证 data.yaml 可读 | 新建 |
| `scripts/train_yolo_v2.py` | 双类模型训练入口 | 新建 |
| `scripts/eval_detector.py` | 按图片列表评测模型的图级召回 | 新建 |
| `backend/app/tiling.py` | 切片推理核心：分片与跨片合并（纯函数，可单测） | 新建 |
| `backend/tests/test_tiling.py` | 切片与合并的单元测试 | 新建 |
| `backend/app/detector.py` | 增加切片推理入口 `detect_tiled` | 修改 |
| `backend/app/worker.py` | 按间隔决定走整图还是切片 | 修改 |
| `backend/app/db.py` | 新增 4 个切片配置项的读写 | 修改 |
| `backend/app/main.py` | 设置接口支持切片配置；检测事件带 `tiled` 标记 | 修改 |
| `frontend/src/views/SettingsView.vue` | 切片开关与参数 | 修改 |
| `frontend/src/views/MonitorView.vue` | 显示"远距离模式"标记 | 修改 |
| `scripts/eval_tiling.py` | 同一模型下对比整图与切片推理的远景召回 | 新建 |
| `docs/far-field-evaluation.md` | 评估结论 | 新建 |
| `docs/ai-training-records-v2.md` | 双类模型的训练记录 | 新建 |

---

## Task 1: 数据管线

**Files:**
- Create: `scripts/prepare_dfire.py`
- Create: `scripts/check_dataset.py`
- Create: `datasets/fire-smoke-v2/data.yaml`（由脚本生成，不入 Git）

**Interfaces:**
- Consumes: 已解压的 `datasets/d-fire/{train,test}/{images,labels}`
- Produces: `datasets/fire-smoke-v2/data.yaml`（Task 2 训练用）、`farfield.txt`（Task 5 评估用）

- [ ] **Step 1: 写数据管线脚本**

```python
"""把 D-Fire 整理成 ultralytics 可用的数据集描述文件。

不复制图片：用 txt 列表指向原图，避免多占 3GB 磁盘。
val 从 train 里按"编号尾部连续块"切出 10%，避免相邻帧泄漏。
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
D_FIRE = ROOT / "datasets" / "d-fire"
OUT = ROOT / "datasets" / "fire-smoke-v2"
VAL_RATIO = 0.1
SMALL_AREA = 0.01


def has_valid_label(label: Path) -> bool:
    """标注文件存在，且至少有一行非退化的框（宽高 > 0）。"""
    if not label.is_file():
        return False
    for line in label.read_text().splitlines():
        parts = line.split()
        if len(parts) == 5 and float(parts[3]) > 0 and float(parts[4]) > 0:
            return True
    return False


def seq_key(stem: str) -> tuple[str, int]:
    prefix = re.match(r"^([A-Za-z]+)", stem).group(1)
    return prefix, int(re.search(r"(\d+)", stem).group(1))


def collect(split: str) -> list[Path]:
    img_dir = D_FIRE / split / "images"
    return [p for p in sorted(img_dir.glob("*.jpg"))
            if has_valid_label(D_FIRE / split / "labels" / (p.stem + ".txt"))]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    by_prefix: dict[str, list[Path]] = {}
    for p in collect("train"):
        by_prefix.setdefault(seq_key(p.stem)[0], []).append(p)

    val, train = [], []
    for files in by_prefix.values():
        files.sort(key=lambda p: seq_key(p.stem)[1])
        cut = max(1, int(len(files) * VAL_RATIO))
        val.extend(files[-cut:])
        train.extend(files[:-cut])

    test_all = collect("test")
    farfield = []
    for p in test_all:
        label = D_FIRE / "test" / "labels" / (p.stem + ".txt")
        boxes = [ln.split() for ln in label.read_text().splitlines() if ln.strip()]
        ratios = [float(b[3]) * float(b[4]) for b in boxes if len(b) == 5]
        if ratios and all(r < SMALL_AREA for r in ratios):
            farfield.append(p)

    def dump(name: str, files: list[Path]) -> None:
        (OUT / name).write_text("\n".join(p.as_posix() for p in files), encoding="utf-8")

    dump("train.txt", train)
    dump("val.txt", val)
    dump("test.txt", test_all)
    dump("farfield.txt", farfield)
    (OUT / "data.yaml").write_text(
        "path: {p}\ntrain: {t}\nval: {v}\ntest: {s}\nnames:\n  0: smoke\n  1: fire\n".format(
            p=OUT.as_posix(),
            t=(OUT / "train.txt").as_posix(),
            v=(OUT / "val.txt").as_posix(),
            s=(OUT / "test.txt").as_posix(),
        ),
        encoding="utf-8",
    )
    print(f"train {len(train)}  val {len(val)}  test {len(test_all)}  远距离小目标子集 {len(farfield)}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 运行并核对数量**

Run:
```powershell
ai\.venv\Scripts\python scripts\prepare_dfire.py
```

Expected: `train` 与 `val` 之和约 17,221（略少是因为过滤了退化框的图）、`test` 约 4,306。

- [ ] **Step 3: 验证 ultralytics 能读 data.yaml**

```python
"""用 ultralytics 自带函数验证 data.yaml 可读、类别数为 2。"""
from pathlib import Path

from ultralytics.data.utils import check_det_dataset

data = check_det_dataset(str(Path("datasets/fire-smoke-v2/data.yaml")))
print("names:", data["names"])
assert len(data["names"]) == 2, "类别数应为 2"
print("OK")
```

Run:
```powershell
ai\.venv\Scripts\python scripts\check_dataset.py
```

Expected: 打印 `names: {0: 'smoke', 1: 'fire'}` 与 `OK`。
若报路径找不到，说明 ultralytics 不接受 txt 列表：退回到"移动文件"方案——在 `datasets/d-fire/` 下建 `train/`、`val/`、`test/` 三个目录并移动图片与标注，`data.yaml` 改指向目录。

- [ ] **Step 4: 提交**

```bash
git add scripts/prepare_dfire.py scripts/check_dataset.py
git commit -m "feat(data): D-Fire 数据管线与数据集描述文件 - 蔡俊杰"
```

（`datasets/` 被 gitignore，只提交脚本。）

---

## Task 2: 训练双类模型并评测

**Files:**
- Create: `scripts/train_yolo_v2.py`
- Create: `scripts/eval_detector.py`
- Create: `docs/ai-training-records-v2.md`

**Interfaces:**
- Consumes: `datasets/fire-smoke-v2/data.yaml`
- Produces: `ai/runs/fire26n-v2/weights/best.pt`（系统与 Task 5 使用）、`scripts/eval_detector.py`（Task 2 与 Task 5 复用）

- [ ] **Step 1: 写训练入口**

```python
"""训练 fire+smoke 双类模型（YOLO26n，RTX 4050 6GB）。"""
from __future__ import annotations

import argparse

from ultralytics import YOLO


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="yolo26n.pt")
    ap.add_argument("--data", default="datasets/fire-smoke-v2/data.yaml")
    ap.add_argument("--epochs", type=int, default=80)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--name", default="fire26n-v2")
    args = ap.parse_args()

    model = YOLO(args.model)
    model.train(
        data=args.data, epochs=args.epochs, imgsz=args.imgsz, batch=args.batch,
        name=args.name, device=0, workers=0, patience=20, seed=42, amp=True,
    )


if __name__ == "__main__":
    main()
```

（`workers=0` 是首轮训练的经验：Windows 多进程 DataLoader 会触发 WinError 1455。）

- [ ] **Step 2: 先跑 1 个 epoch 验证管线**

Run:
```powershell
$env:FIREGUARD_DEVICE='0'
ai\.venv\Scripts\python scripts\train_yolo_v2.py --epochs 1 --name fire26n-v2-trial
```

Expected: 完成 1 个 epoch 并打印 mAP。若报 CUDA out of memory，把 `--batch` 降到 4 重跑。

- [ ] **Step 3: 正式训练**

Run（预计 40~80 分钟，可用后台方式执行，同时并行推进 Task 3）：
```powershell
$env:FIREGUARD_DEVICE='0'
ai\.venv\Scripts\python scripts\train_yolo_v2.py --epochs 80 --name fire26n-v2
```

Expected: 生成 `ai/runs/fire26n-v2/weights/best.pt`。

- [ ] **Step 4: 写评测脚本**

```python
"""在指定图片列表上评测模型：按类别统计图级召回。"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[1]


def read_bgr(path: Path):
    with Image.open(path) as im:
        return np.array(im.convert("RGB"))[:, :, ::-1].copy()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", required=True)
    ap.add_argument("--list", required=True)
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--limit", type=int, default=0, help="0 表示全量")
    args = ap.parse_args()

    files = [Path(p) for p in Path(args.list).read_text(encoding="utf-8").splitlines() if p.strip()]
    if args.limit:
        files = files[: args.limit]
    model = YOLO(args.weights)
    hit, total = {0: 0, 1: 0}, {0: 0, 1: 0}
    for f in files:
        label = f.parent.parent / "labels" / (f.stem + ".txt")
        want = {int(ln.split()[0]) for ln in label.read_text().splitlines() if ln.strip()}
        for c in want:
            total[c] += 1
        res = model.predict(read_bgr(f), imgsz=640, conf=args.conf, device=0, verbose=False)[0]
        got = {int(c) for c in res.boxes.cls.tolist()} if res.boxes is not None else set()
        for c in want & got:
            hit[c] += 1
    for c, name in ((0, "smoke"), (1, "fire")):
        if total[c]:
            print(f"{name}({c}): 图级召回 {hit[c]}/{total[c]} = {hit[c]/total[c]*100:.1f}%  (conf>={args.conf})")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: 跑评测，拿到对比数字**

Run:
```powershell
ai\.venv\Scripts\python scripts\eval_detector.py --weights ai\runs\fire26n-v2\weights\best.pt --list datasets\fire-smoke-v2\farfield.txt
ai\.venv\Scripts\python scripts\eval_detector.py --weights ai\runs\fire26n\weights\best.pt --list datasets\fire-smoke-v2\farfield.txt
```

Expected: 新模型两类召回均高于旧模型，且 smoke 类别从"基本为 0"变为可用（旧模型 smoke 基线约 15%）。若新模型在该子集上反而不如旧模型，说明域差异问题成立，按设计文档的应对措施混入近景数据后重跑。

- [ ] **Step 6: 记录并提交**

在 `docs/ai-training-records-v2.md` 记录：数据集与划分、超参、mAP50 / mAP50-95、每类 P/R、小目标子集召回、与旧模型的对比表。

```bash
git add scripts/train_yolo_v2.py scripts/eval_detector.py docs/ai-training-records-v2.md
git commit -m "feat(ai): D-Fire 双类模型训练与评测 - 蔡俊杰"
```

---

## Task 3: 切片推理核心模块

**Files:**
- Create: `backend/app/tiling.py`
- Create: `backend/tests/test_tiling.py`

**Interfaces:**
- Produces:
  - `Tile = namedtuple("Tile", "x y image")`
  - `tile_frame(frame: np.ndarray, tile_size: int = 640, overlap: float = 0.2) -> list[Tile]`
  - `merge_detections(items: list[dict], iou_thr: float = 0.5) -> list[dict]`
  - 检测结果 dict 结构与现有 `YoloDetector.detect` 一致：`{"type": "fire"|"smoke", "confidence": float, "bbox": [x, y, w, h]}`，坐标为**全图坐标**

- [ ] **Step 1: 写失败测试**

```python
import numpy as np

from backend.app.tiling import merge_detections, tile_frame


def test_tile_frame_covers_whole_image():
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    tiles = tile_frame(frame, tile_size=640, overlap=0.2)
    assert len(tiles) >= 4
    assert min(t.x for t in tiles) == 0
    assert min(t.y for t in tiles) == 0
    assert max(t.x + t.image.shape[1] for t in tiles) == 1280
    assert max(t.y + t.image.shape[0] for t in tiles) == 720


def test_tile_frame_handles_small_image():
    frame = np.zeros((300, 400, 3), dtype=np.uint8)
    tiles = tile_frame(frame, tile_size=640, overlap=0.2)
    assert len(tiles) == 1
    assert tiles[0].image.shape[:2] == (300, 400)


def test_merge_keeps_highest_confidence_for_same_box():
    dets = [
        {"type": "fire", "confidence": 0.6, "bbox": [10, 10, 50, 50]},
        {"type": "fire", "confidence": 0.9, "bbox": [12, 12, 50, 50]},
        {"type": "smoke", "confidence": 0.7, "bbox": [200, 200, 80, 80]},
    ]
    merged = merge_detections(dets, iou_thr=0.5)
    assert len(merged) == 2
    assert [d for d in merged if d["type"] == "fire"][0]["confidence"] == 0.9


def test_merge_keeps_different_classes_separate():
    dets = [
        {"type": "fire", "confidence": 0.8, "bbox": [0, 0, 50, 50]},
        {"type": "smoke", "confidence": 0.8, "bbox": [5, 5, 50, 50]},
    ]
    assert len(merge_detections(dets, iou_thr=0.5)) == 2
```

- [ ] **Step 2: 运行确认失败**

Run: `ai\.venv\Scripts\python -m pytest backend/tests/test_tiling.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'backend.app.tiling'`

- [ ] **Step 3: 实现 tiling 模块**

```python
"""切片推理：把大图切成瓦片分别检测，再把结果合并回全图。"""
from __future__ import annotations

from collections import namedtuple
from typing import Any

import numpy as np

Tile = namedtuple("Tile", "x y image")


def _axis_starts(length: int, tile: int, step: int) -> list[int]:
    if length <= tile:
        return [0]
    starts = list(range(0, length - tile + 1, step))
    if starts[-1] != length - tile:      # 保证最后一片贴住边界
        starts.append(length - tile)
    return sorted(set(starts))


def tile_frame(frame: np.ndarray, tile_size: int = 640, overlap: float = 0.2) -> list[Tile]:
    """按固定步长切图，保证四条边都被覆盖；小图直接返回整图。"""
    h, w = frame.shape[:2]
    step = max(1, int(tile_size * (1 - overlap)))
    tiles: list[Tile] = []
    for y in _axis_starts(h, tile_size, step):
        for x in _axis_starts(w, tile_size, step):
            tiles.append(Tile(x, y, frame[y:y + tile_size, x:x + tile_size]))
    return tiles


def _iou(a: list[int], b: list[int]) -> float:
    ax1, ay1, aw, ah = a
    bx1, by1, bw, bh = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax1 + aw, bx1 + bw), min(ay1 + ah, by1 + bh)
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    if inter <= 0:
        return 0.0
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def merge_detections(items: list[dict[str, Any]], iou_thr: float = 0.5) -> list[dict[str, Any]]:
    """同一类别内按置信度降序做 NMS；不同类别互不抑制。"""
    kept: list[dict[str, Any]] = []
    for item in sorted(items, key=lambda d: d["confidence"], reverse=True):
        if any(k["type"] == item["type"] and _iou(k["bbox"], item["bbox"]) >= iou_thr for k in kept):
            continue
        kept.append(item)
    return kept
```

- [ ] **Step 4: 运行确认通过**

Run: `ai\.venv\Scripts\python -m pytest backend/tests/test_tiling.py -q`
Expected: `4 passed`

- [ ] **Step 5: 提交**

```bash
git add backend/app/tiling.py backend/tests/test_tiling.py
git commit -m "feat(backend): 切片推理与跨片合并模块 - 蔡俊杰"
```

---

## Task 4: 接入检测链路与系统配置

**Files:**
- Modify: `backend/app/detector.py`
- Modify: `backend/app/worker.py`
- Modify: `backend/app/db.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_api.py`
- Modify: `frontend/src/views/SettingsView.vue`、`frontend/src/views/MonitorView.vue`

**Interfaces:**
- Consumes: Task 3 的 `tile_frame` / `merge_detections`
- Produces: 设置项 `tiling_enabled`(0/1)、`tile_size`(int)、`tile_overlap`(float)、`tile_interval`(int 秒)

- [ ] **Step 1: detector 增加切片入口**

在 `YoloDetector` 中把 `conf` 提为形参（默认 0.05），并新增：

```python
    def detect_tiled(self, frame, tile_size: int = 640, overlap: float = 0.2,
                     iou_thr: float = 0.5) -> list[dict[str, Any]]:
        """切片推理：逐片检测后把坐标平移回全图并合并。"""
        from .tiling import merge_detections, tile_frame

        merged: list[dict[str, Any]] = []
        for tile in tile_frame(frame, tile_size, overlap):
            for det in self.detect(tile.image):
                x, y, w, h = det["bbox"]
                merged.append({
                    "type": det["type"],
                    "confidence": det["confidence"],
                    "bbox": [x + tile.x, y + tile.y, w, h],
                })
        return merge_detections(merged, iou_thr)
```

- [ ] **Step 2: worker 按间隔触发切片**

把内层循环里的 `s = self.settings_provider()` 与 `objects = self.detector.detect(frame)` 换成：

```python
                s = self.settings_provider()
                use_tiling = bool(int(s.get("tiling_enabled", 0))) and (
                    now - getattr(self, "_last_tile_ts", 0.0) >= float(s.get("tile_interval", 2))
                )
                if use_tiling:
                    objects = self.detector.detect_tiled(
                        frame,
                        tile_size=int(s.get("tile_size", 640)),
                        overlap=float(s.get("tile_overlap", 0.2)),
                    )
                    self._last_tile_ts = now
                else:
                    objects = self.detector.detect(frame)
```

并在该帧的检测事件中加字段 `"tiled": use_tiling`。

- [ ] **Step 3: 配置项与接口**

`db.init_db` 的默认设置补四项：`tiling_enabled="1"`、`tile_size="640"`、`tile_overlap="0.2"`、`tile_interval="2"`；
`get_settings` / `put_settings` 同步支持（布尔转 0/1、浮点转 float、整数转 int）；
`main.py` 的 `SettingsPayload` 增加对应字段，约束：`tile_size` 320~1280、`tile_overlap` 0~0.5、`tile_interval` 1~10。

- [ ] **Step 4: 后端测试**

在 `backend/tests/test_api.py` 增加：

```python
def test_settings_include_tiling(client):
    data = client.get("/api/settings").json()
    assert "tiling_enabled" in data
    assert float(data["tile_overlap"]) <= 0.5
```

Run: `ai\.venv\Scripts\python -m pytest backend/tests -q`
Expected: 全部通过（原有 6 个 + 新增 1 个 + Task 3 的 4 个）。

- [ ] **Step 5: 前端**

- `SettingsView.vue`：加 `el-switch`（远距离模式）+ 三个 `el-input-number`（瓦片尺寸、重叠率、扫描间隔），并入现有 `saveSettings` 请求体。
- `MonitorView.vue`：处理 WebSocket 检测事件时读取 `msg.tiled`，页面显示"远距离模式"标签（开启时高亮）。

- [ ] **Step 6: 构建与手工验证**

Run: `cd frontend; npm run build`
Expected: 构建通过。

随后启动后端与前端，在设置页开关"远距离模式"，观察监控页标签与检出框变化。

- [ ] **Step 7: 提交**

```bash
git add backend/app backend/tests frontend/src
git commit -m "feat(system): 切片推理接入检测链路并开放配置 - 蔡俊杰"
```

---

## Task 5: 对比评估与演示材料

**Files:**
- Create: `scripts/eval_tiling.py`
- Create: `docs/far-field-evaluation.md`

**Interfaces:**
- Consumes: `datasets/fire-smoke-v2/farfield.txt`、`ai/runs/fire26n-v2/weights/best.pt`、`backend/app/tiling.py`

- [ ] **Step 1: 写对比评估脚本**

```python
"""同一模型、同一小目标子集上，对比整图推理与切片推理的图级召回与耗时。"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
from PIL import Image
from ultralytics import YOLO

from backend.app.tiling import merge_detections, tile_frame


def read_bgr(path: Path):
    with Image.open(path) as im:
        return np.array(im.convert("RGB"))[:, :, ::-1].copy()


def detect(model, frame, conf):
    res = model.predict(frame, imgsz=640, conf=conf, device=0, verbose=False)[0]
    if res.boxes is None:
        return []
    out = []
    for box, c, ci in zip(res.boxes.xyxy.cpu().numpy(), res.boxes.conf.cpu().numpy(),
                          res.boxes.cls.cpu().numpy()):
        x1, y1, x2, y2 = map(float, box)
        out.append({
            "type": "fire" if int(ci) == 1 else "smoke",
            "confidence": float(c),
            "bbox": [round(x1), round(y1), round(x2 - x1), round(y2 - y1)],
        })
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", required=True)
    ap.add_argument("--list", default="datasets/fire-smoke-v2/farfield.txt")
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--limit", type=int, default=200)
    args = ap.parse_args()

    files = [Path(p) for p in Path(args.list).read_text(encoding="utf-8").splitlines() if p.strip()]
    files = files[: args.limit]
    model = YOLO(args.weights)
    plain_hit = tiled_hit = 0
    plain_t = tiled_t = 0.0
    for i, f in enumerate(files, 1):
        img = read_bgr(f)
        t0 = time.perf_counter()
        if detect(model, img, args.conf):
            plain_hit += 1
        plain_t += time.perf_counter() - t0

        t0 = time.perf_counter()
        merged = []
        for tile in tile_frame(img, 640, 0.2):
            for d in detect(model, tile.image, args.conf):
                x, y, w, h = d["bbox"]
                merged.append({**d, "bbox": [x + tile.x, y + tile.y, w, h]})
        if merge_detections(merged, 0.5):
            tiled_hit += 1
        tiled_t += time.perf_counter() - t0
        if i % 20 == 0:
            print(f"  已处理 {i}/{len(files)}")

    n = len(files)
    print(f"整图推理: 图级召回 {plain_hit}/{n} = {plain_hit/n*100:.1f}%   平均 {plain_t/n*1000:.0f} ms/帧")
    print(f"切片推理: 图级召回 {tiled_hit}/{n} = {tiled_hit/n*100:.1f}%   平均 {tiled_t/n*1000:.0f} ms/帧")
    print(f"召回提升: {(tiled_hit - plain_hit)/n*100:+.1f} 个百分点")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 运行评估**

Run:
```powershell
$env:FIREGUARD_DEVICE='0'
ai\.venv\Scripts\python scripts\eval_tiling.py --weights ai\runs\fire26n-v2\weights\best.pt --limit 200
```

Expected: 打印两种推理方式的召回与耗时。若切片没有提升，把 `--conf` 降到 0.1 再跑一次，并如实记录两种条件下的结果。

- [ ] **Step 3: 写评估结论**

`docs/far-field-evaluation.md` 记录：评估集构成（样本数、都是小目标）、两种推理方式的召回与平均耗时、结论与局限（合成/小目标子集不能完全代表真实远景）。

- [ ] **Step 4: 准备演示素材**

从 D-Fire 的 AoF 序列挑一段远景图序列合成为短视频，或直接用手机拍一段远景，放入 `storage/uploads/`；在演示脚本中固定"关闭远距离模式 → 开启 → 对比检出"的流程。

- [ ] **Step 5: 提交**

```bash
git add scripts/eval_tiling.py docs/far-field-evaluation.md
git commit -m "feat(eval): 整图与切片推理的远景对比评估 - 蔡俊杰"
```

---

## 自检清单（全部任务完成后逐条确认）

- [ ] 模型能同时检出 fire 与 smoke，且小目标子集召回高于旧模型（Task 2 Step 5 的数字）
- [ ] 切片推理在远景子集上相对整图推理有提升（Task 5 Step 2 的数字）
- [ ] 系统设置页可控制切片开关与参数，监控页显示远距离标记（Task 4 Step 6）
- [ ] `ai\.venv\Scripts\python -m pytest backend/tests -q` 全绿
- [ ] `cd frontend; npm run build` 通过
- [ ] `docs/ai-training-records-v2.md` 与 `docs/far-field-evaluation.md` 已提交
