# FireGuard AI 双类烟火模型训练记录（v2）

- 日期：2026-10-20 至 2026-10-21
- 权重：`ai/runs/fire26n-v2/weights/best.pt`
- 训练日志：`ai/runs/fire26n-v2/results.csv`
- 评测原始结果：`ai/runs/eval-v2.json`

## 1. 训练目标

旧模型只检测 fire 一类，且训练集以近景为主，无法覆盖烟雾和远景小目标。本轮训练使用 D-Fire 双类数据训练 YOLO26n，目标是：

1. 同时识别 smoke 与 fire；
2. 提升远景小目标召回；
3. 在新模型基础上接入切片推理与告警复核，降低误报。

## 2. 数据

| 项目 | 数值 |
| --- | --- |
| 数据集 | D-Fire（CC0） |
| 总图片 | 21,527 |
| 训练 / 验证 / 测试 | 15,500 / 1,721 / 4,306 |
| 负样本 | 9,838 |
| 类别 | 0 = smoke，1 = fire |
| 框数 | smoke 11,865，fire 14,692 |
| 远景子集 | test 中 520 张，全部框面积 < 1% |

预处理：

- 空标注保留为负样本，只剔除宽或高为 0 的退化框；
- 图片长边预缩放到 640，降低 Windows 单进程训练的解码开销；
- 验证集从每个编号前缀的中段连续块切出 10%，避免直接用尾部造成负样本比例失真。

## 3. 训练配置

| 参数 | 值 |
| --- | --- |
| 模型 | YOLO26n（2.5M 参数） |
| 输入尺寸 | 640 |
| batch | 8 |
| epochs | 20（best 出现在第 17 轮） |
| 优化器 | AdamW（Ultralytics auto） |
| AMP | 开启 |
| workers | 0（Windows 页文件不足，禁用多进程） |
| seed | 42 |
| 硬件 | RTX 4050 Laptop 6GB |
| 环境 | Ultralytics 8.4.145 / torch 2.11.0+cu128 |

训练中断过两次：一次是系统休眠，一次是 Project/Java 与训练同时占用内存导致 OOM；都从 `last.pt` 断点续训，最终完成 20 轮。

## 4. 结果

### 4.1 验证集（第 17 轮 best.pt）

| 类别 | Precision | Recall | mAP50 | mAP50-95 |
| --- | --- | --- | --- | --- |
| all | 0.704 | 0.612 | 0.680 | 0.373 |
| smoke | 0.764 | 0.646 | 0.729 | 0.430 |
| fire | 0.645 | 0.578 | 0.631 | 0.316 |

### 4.2 官方 test

4 条标注坐标越界的图片被 Ultralytics 忽略，实际评测 4,302 张 / 5,182 个实例。

| 指标 | 数值 |
| --- | --- |
| Precision | 0.716 |
| Recall | 0.664 |
| mAP50 | **0.724** |
| mAP50-95 | 0.400 |

官方 test mAP50 达到需求规格说明书的 ≥0.70 验收线。

### 4.3 SmokeFire 跨数据集评测

在欧阳宇康补交的 SmokeFire（3,680 张可用标注图，未参与训练）上，conf≥0.25：

| 类别 | 图级召回 |
| --- | --- |
| smoke | 90.8%（3,032 / 3,338） |
| fire | 90.5%（1,656 / 1,830） |

说明模型对未参与训练的烟雾数据有较好的泛化能力。

## 5. 与旧模型对比

| 评测项 | 旧模型（fire 单类） | 新模型（fire+smoke） |
| --- | --- | --- |
| D-Fire 远景小目标图级召回（520 张，conf 0.25） | 18.5% | **81.2%** |
| 困难负样本图级误报（2,469 张，conf 0.25） | 52.7% | **34.2%** |
| smoke 类 | 基本不可用 | test mAP50 0.729，SmokeFire 召回 90.8% |

## 6. 复现

```powershell
ai\.venv\Scripts\python scripts\prepare_dfire.py
ai\.venv\Scripts\python scripts\build_resized_dataset.py
$env:FIREGUARD_DEVICE='0'
ai\.venv\Scripts\python scripts\train_yolo_v2.py --data datasets/fire-smoke-v2-640/data.yaml --epochs 20 --batch 8 --workers 0 --name fire26n-v2
ai\.venv\Scripts\python scripts\evaluate_v2.py
```

## 7. 遗留问题

- 4 条 test 标注存在越界坐标，当前被验证器忽略；后续应在数据管线中做坐标裁剪；
- 困难负样本在 0.25 阈值下仍有 34.2% 图级误报，需配合 0.40 / 0.45 阈值、连续帧和局部复核使用；
- 训练吞吐受 6GB 低功耗 GPU 和 Windows 单进程 DataLoader 限制，不适合继续盲目加轮数。
