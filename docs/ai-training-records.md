# AI 训练实验记录

## 实验 1：YOLO26n 首轮训练

- 训练日期：2026-09-09 ~ 2026-09-10
- 数据集：gengyanlei 烟火检测 VOC2020（学术探索用途，来源见仓库 README_ZN）
- 数据集统计：Annotations 2059 / JPEGImages 2059；类别仅 `fire`（3299 个框），**无 smoke 标注**
- 环境：Python 3.12 venv（ai/.venv）、PyTorch 2.11.0+cu128、Ultralytics 8.4.145、NVIDIA RTX 4050 Laptop 6GB
- 模型：YOLO26n（预训练权重微调，2.5M 参数）
- 数据划分：train 1750 / val 309（seed=42，85/15）
- 超参：imgsz=640，epochs 100（配置），batch=16 首轮 → 内存问题后从 epoch 11 起 batch=8 续训，patience=20，seed=42，AMP=True，workers=0
- 停止情况：训练推进至 epoch 88 后进程在收尾阶段被系统中断（未生成最终曲线图）；最佳指标出现在 epoch 68，best.pt 已保存且复验一致
- 验证指标（best.pt，CPU 复验 val 309 张）：
  - mAP50 = **0.758**
  - mAP50-95 = **0.424**
  - Precision = **0.759**
  - Recall = **0.699**
- 权重路径：`ai/runs/fire26n/weights/best.pt`（不入 Git，体积 5.2MB）
- 过程数据：`ai/runs/fire26n/results.csv`（每 epoch 指标）；曲线图未生成，可后续用 results.csv 绘制

## 过程记录与遗留问题

- 训练期间修复的问题：Windows 多进程 DataLoader 触发 WinError 1455 → 改 workers=0；系统内存/页面文件被占满导致一次中断 → 从断点续训并降低 batch。
- 置信度校准问题：该权重在多数图片上的分类置信度偏低（部分图最高仅 0.07，少数图可达 0.8+）。后端推理下限取 0.05，告警阈值默认取 0.1；若换用更大模型或更多数据重训，应重新校准阈值。
- 遗留问题 1：数据集仅 fire 单类，smoke 检测暂由基线模型（D-Fire / gengyanlei yolov5）兜底；补入烟类标注数据的第二轮训练待排期。
- 遗留问题 2：教室"翻拍屏幕"场景下的定性测试待做（素材准备好后用小脚本验证出框稳定性）。
- 对比基线（D-Fire YOLOv8n、gengyanlei yolov5 best.pt）评测待第 5~6 周补充到本文件或独立对比报告。
