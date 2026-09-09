# 烟火数据集准备与 YOLO 首轮训练 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在成员 A 的 RTX 4050（6GB）笔记本上搭建 CUDA 训练环境，将 gengyanlei 烟火数据集（VOC2020）转为 Ultralytics YOLO 格式，完成首轮 YOLO26n 训练与验证，产出可对比的指标记录。

**Architecture:** Python 独立虚拟环境 `ai/.venv`（不影响系统 Python）；VOC XML 由 `scripts/voc2yolo.py` 转换为 YOLO txt 并划分训练/验证集；`scripts/train_yolo.py` 基于 Ultralytics 官方 API 训练并自动验证。数据与权重体积大，不入 Git。

**Tech Stack:** Python 3.12、PyTorch（CUDA）、Ultralytics、OpenCV、Pascal VOC 数据集

## Global Constraints

- 显卡：NVIDIA GeForce RTX 4050 Laptop GPU，显存 6141 MiB（实测），驱动/CUDA 环境允许 CUDA 13.x；当前系统 Python 仅 CPU torch，必须使用独立 venv 安装 CUDA 版。
- 数据集：gengyanlei 烟火检测 VOC2020（Annotations XML + JPEGImages + ImageSets），学术用途仅限学术探索，须在报告标注来源与声明。
- 默认模型：Ultralytics 当前稳定版 **YOLO26n**（官方文档示例型号，适配 6GB 显存）；若下载/兼容失败回退 `yolo11s.pt`。
- 类别不预设：以实际 XML 标注统计结果为准（`fire` 或 `fire+smoke`），脚本自动生成 `nc/names`。
- 除数据集手动下载外，所有步骤可在仓库根目录下以 PowerShell 执行。
- 每个任务结束提交 Git（`.venv`、`datasets/`、`runs/`、权重不入库）。

## File Structure

```
datasets/
├─ fire-smoke-voc/VOC2020/         # 手动下载解压：Annotations/ JPEGImages/ ImageSets/
├─ fire-smoke-yolo/                # voc2yolo 输出：images/ labels/ data.yaml
└─ reports/                        # voc_stats.json
ai/
├─ .venv/                          # CUDA 训练环境（gitignored）
└─ runs/                           # Ultralytics 训练输出（gitignored）
scripts/
├─ inspect_voc.py                  # 统计 XML 类别分布
├─ voc2yolo.py                     # VOC → YOLO txt + 数据集划分 + data.yaml
└─ train_yolo.py                   # 训练 + 自动验证
```

---

### Task 1: 目录与 .gitignore 准备

**Files:**
- Create: `datasets/fire-smoke-voc/`、`datasets/reports/`、`ai/runs/`（目录）
- Modify: `.gitignore`

**Interfaces:**
- Consumes: 无。
- Produces: 后续任务固定目录；训练产物不入库规则。

- [ ] **Step 1: 创建目录**

PowerShell（仓库根目录）：

```powershell
New-Item -ItemType Directory -Force -Path "datasets\fire-smoke-voc", "datasets\fire-smoke-yolo", "datasets\reports", "ai\runs" | Out-Null
```

- [ ] **Step 2: 更新 .gitignore**

在 `.gitignore` 的 `# 数据集与权重` 小节追加：

```gitignore
runs/
```

提交前先 `git add .gitignore` 后执行第 3 步提交。

- [ ] **Step 3: 提交**

```bash
git add .gitignore
git commit -m "chore(ai): 准备数据集与训练输出目录"
```

---

### Task 2: 创建 CUDA 训练环境并验证 GPU

**Files:**
- Create: `ai/.venv/`

**Interfaces:**
- Consumes: Task 1 目录。
- Produces: `ai/.venv/Scripts/python`（含 CUDA torch 与 ultralytics）；后续所有 Python 命令均使用该解释器。

- [ ] **Step 1: 创建虚拟环境**

PowerShell：

```powershell
python -m venv ai\.venv
ai\.venv\Scripts\python -m pip install --upgrade pip
```

- [ ] **Step 2: 安装 CUDA 版 PyTorch**

```powershell
ai\.venv\Scripts\python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
```

若该索引无当前 torch 版本导致报错，改为访问 https://pytorch.org/get-started/locally/ 取最新 CUDA 索引 URL 后重试（允许的偏差仅限此 URL 与 cu 版本号）。

- [ ] **Step 3: 验证 GPU 可用**

```powershell
ai\.venv\Scripts\python -c "import torch; print(torch.__version__); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0))"
```

预期输出：版本号、`True`、`NVIDIA GeForce RTX 4050 Laptop GPU`。若为 `False`，停止并排查（驱动需 ≥ 对应 CUDA 版本要求，本机驱动 610.88 满足 cu128+）。

- [ ] **Step 4: 安装 Ultralytics**

```powershell
ai\.venv\Scripts\python -m pip install ultralytics
ai\.venv\Scripts\python -c "from ultralytics import YOLO; print('ultralytics ok')"
```

预期：`ultralytics ok`。

- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "chore(ai): 准备 CUDA 训练虚拟环境（venv 不入库）"
```

---

### Task 3: 下载并放置数据集

**Files:**
- Create: `datasets/fire-smoke-voc/VOC2020/Annotations/`、`JPEGImages/`、`ImageSets/Main/`

**Interfaces:**
- Consumes: Task 1 目录。
- Produces: 供 Task 4 统计的原始数据集。

- [ ] **Step 1: 组员手动下载**

按数据集仓库 README_ZN.md 的百度网盘链接（提取码见仓库说明）下载烟火检测数据集压缩包；Windows 下用 7-Zip 解压（如 README 提示需解压两次）。

- [ ] **Step 2: 放置到约定目录**

确认最终目录结构为：

```text
datasets/fire-smoke-voc/VOC2020/
├─ Annotations/   (xml_num ≈ 2059)
├─ JPEGImages/    (image_num ≈ 2059)
└─ ImageSets/Main/
```

- [ ] **Step 3: 验证结构**

```powershell
Get-ChildItem datasets\fire-smoke-voc\VOC2020\Annotations | Measure-Object | Select-Object -ExpandProperty Count
Get-ChildItem datasets\fire-smoke-voc\VOC2020\JPEGImages | Measure-Object | Select-Object -ExpandProperty Count
```

预期：两个计数一致且约为 2059（允许与仓库版本有少量出入）。不一致则先解决数据问题再继续。

---

### Task 4: 类别统计脚本并生成报告

**Files:**
- Create: `scripts/inspect_voc.py`
- Create: `datasets/reports/voc_stats.json`（运行产物）

**Interfaces:**
- Consumes: `datasets/fire-smoke-voc/VOC2020/Annotations`（XML）。
- Produces: `voc_stats.json`：`{xml_count, image_count, class_counts, classes}`，决定后续 `nc/names`。

- [ ] **Step 1: 写入统计脚本**

创建 `scripts/inspect_voc.py`：

```python
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
```

- [ ] **Step 2: 运行统计**

```powershell
python scripts\inspect_voc.py
```

预期：终端打印 JSON 报告，`xml_count` 与 `image_count` 约 2059，`classes` 至少含 `fire`；`datasets/reports/voc_stats.json` 生成。

- [ ] **Step 3: 按结果记录数据决策**

在 Git 提交信息或 docs 记录实际类别分布，作为后续训练与对比报告的输入。

- [ ] **Step 4: 提交**

```bash
git add scripts/inspect_voc.py datasets/reports/voc_stats.json
git commit -m "feat(ai): VOC 数据类别统计脚本与报告"
```

---

### Task 5: VOC → YOLO 转换与数据集划分

**Files:**
- Create: `scripts/voc2yolo.py`
- Create: `datasets/fire-smoke-yolo/data.yaml` 及 `images/{train,val}`、`labels/{train,val}`（运行产物）

**Interfaces:**
- Consumes: Task 4 输出的类别事实（脚本自动读取 XML，不依赖 JSON）。
- Produces: `data.yaml`（含绝对路径）；训练脚本 Task 7 读取该文件。

- [ ] **Step 1: 写入转换脚本**

创建 `scripts/voc2yolo.py`：

```python
from __future__ import annotations

import random
import shutil
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

        width, height, objects = parse_xml(xml)
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
```

- [ ] **Step 2: 运行转换**

```powershell
python scripts\voc2yolo.py
```

预期：打印 `class_names`（来自真实标注）、train/val 数量，且 `datasets/fire-smoke-yolo/data.yaml` 生成。

- [ ] **Step 3: 提交**

```bash
git add scripts/voc2yolo.py
git commit -m "feat(ai): VOC 转 YOLO 格式脚本与数据集划分"
```

（转换产物在 `datasets/` 下，按 .gitignore 不入库。）

---

### Task 6: 转换结果校验

**Files:** 无新增

**Interfaces:**
- Consumes: Task 5 产物。
- Produces: 可训练数据集的核对结论。

- [ ] **Step 1: 统计文件数量**

```powershell
(Get-ChildItem datasets\fire-smoke-yolo\images\train).Count
(Get-ChildItem datasets\fire-smoke-yolo\labels\train).Count
(Get-ChildItem datasets\fire-smoke-yolo\images\val).Count
(Get-ChildItem datasets\fire-smoke-yolo\labels\val).Count
```

预期：train 图片数 = train 标签数，val 图片数 = val 标签数。

- [ ] **Step 2: 抽查标注行**

```powershell
Get-Content (Get-ChildItem datasets\fire-smoke-yolo\labels\train\*.txt | Select-Object -First 1).FullName
```

预期：每行格式 `class x_center y_center width height`，数值均在 0~1。

---

### Task 7: 首轮训练（YOLO26n）

**Files:**
- Create: `scripts/train_yolo.py`
- Create: `ai/runs/fire26n/`（运行产物）

**Interfaces:**
- Consumes: `datasets/fire-smoke-yolo/data.yaml`（Task 5）。
- Produces: `ai/runs/fire26n/weights/best.pt`、`results.csv`、`args.yaml`；`best.pt` 供后端检测 worker 加载与后续对比。

- [ ] **Step 1: 写入训练脚本**

创建 `scripts/train_yolo.py`：

```python
from __future__ import annotations

import argparse
from pathlib import Path

from ultralytics import YOLO


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="yolo26n.pt", help="预训练权重名或路径")
    parser.add_argument("--name", default="fire26n")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--imgsz", type=int, default=640)
    args = parser.parse_args()

    data_yaml = root / "datasets" / "fire-smoke-yolo" / "data.yaml"
    if not data_yaml.is_file():
        raise SystemExit(f"缺少 data.yaml: {data_yaml}")

    model = YOLO(args.model)
    model.train(
        data=str(data_yaml),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=0,
        patience=20,
        seed=42,
        amp=True,
        project=str(root / "ai" / "runs"),
        name=args.name,
        exist_ok=True,
    )
    metrics = model.val(data=str(data_yaml), split="val")
    print(f"mAP50={metrics.box.map50:.4f} mAP50-95={metrics.box.map:.4f}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 启动训练**

从仓库根目录执行：

```powershell
ai\.venv\Scripts\python scripts\train_yolo.py --model yolo26n.pt --name fire26n
```

首次会自动下载 `yolo26n.pt` 预训练权重（需联网）。若下载/加载失败（型号不存在），回退执行：

```powershell
ai\.venv\Scripts\python scripts\train_yolo.py --model yolo11s.pt --name fire11s
```

预期训练时长：RTX 4050 + 约 1750 张训练图 + batch 16 + 100 epochs，约 0.5~2 小时（含 early stop）。若当次实训时间不足，训练可后台挂着，下个任务用断点恢复继续：

```powershell
ai\.venv\Scripts\python -c "from ultralytics import YOLO; YOLO('ai/runs/fire26n/weights/last.pt').train(resume=True)"
```

- [ ] **Step 3: 提交训练脚本**

训练启动并确认无立即报错后：

```bash
git add scripts/train_yolo.py
git commit -m "feat(ai): YOLO 训练脚本（可配模型/批次/epochs）"
```

---

### Task 8: 验证结果并记录指标

**Files:**
- Create: `docs/ai-training-records.md`（记录实验）

**Interfaces:**
- Consumes: Task 7 的 `runs/fire26n/weights/best.pt`。
- Produces: 训练实验记录（数据版本、模型、指标、结论），供第 5~6 周模型对比报告引用。

- [ ] **Step 1: 确认训练正常结束**

```powershell
Test-Path ai\runs\fire26n\weights\best.pt
Get-Content ai\runs\fire26n\results.csv | Select-Object -Last 2
```

预期：`best.pt` 存在；`results.csv` 末两行含 epochs、`mAP50(B)`、`mAP50-95(B)` 等数值。

- [ ] **Step 2: 单独跑一次验证**

```powershell
ai\.venv\Scripts\python -c "from ultralytics import YOLO; m=YOLO('ai/runs/fire26n/weights/best.pt').val(data='datasets/fire-smoke-yolo/data.yaml', split='val'); print('mAP50', round(m.box.map50,4), 'mAP50-95', round(m.box.map,4), 'P', round(m.box.mp,4), 'R', round(m.box.mr,4))"
```

预期：打印验证集 mAP50 / mAP50-95 / 平均 Precision / 平均 Recall（若 `fire11s` 回退运行，将命令与路径中的 `fire26n` 换成 `fire11s`）。

- [ ] **Step 3: 写实验记录**

创建 `docs/ai-training-records.md`，内容模板如下（按实际结果填写数值）：

```markdown
# AI 训练实验记录

## 实验 1：YOLO26n 首轮训练
- 训练日期：2026-09-09
- 数据集：gengyanlei 烟火检测 VOC2020（学术探索用途，来源见仓库 README_ZN）
- 类别分布：由 datasets/reports/voc_stats.json 提供（如仅含 fire 类，需注明烟类兜底策略）
- 模型：YOLO26n（若回退则 YOLO11s）
- 超参：imgsz=640, batch=16, epochs=100, patience=20, seed=42
- 验证指标：mAP50 = __，mAP50-95 = __，Precision = __，Recall = __
- 权重路径：ai/runs/fire26n/weights/best.pt
- 遗留问题：待补（如烟类数据缺失、翻拍素材待测）
```

其中"遗留问题"由实际训练现象填写，禁止留空提交。

- [ ] **Step 4: 提交**

```bash
git add docs/ai-training-records.md
git commit -m "docs(ai): 首轮训练指标与实验记录"
```
