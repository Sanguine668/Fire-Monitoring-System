# 火情智能监测与预警系统（FireGuard AI）

软件项目管理课程小组实训项目。系统接入手机摄像头、本地上传视频与 RTSP 摄像头，利用自训练深度学习模型实时识别火焰与烟雾，提供分级预警、历史告警、统计分析与系统配置功能。

- 团队：蔡俊杰（组长）、李汶航、欧阳宇康、陈泽恩
- 周期：2026-09-03 ~ 2026-11-05（8 周）
- 仓库：https://github.com/Sanguine668/Fire-Monitoring-System

## 目录结构

| 目录 | 内容 | 说明 |
| --- | --- | --- |
| `backend/` | FastAPI 后端 | 视频源管理、检测 worker、告警引擎、REST/WebSocket/MJPEG 接口 |
| `frontend/` | Vue3 前端 | 监控总览、实时监控、告警中心、视频源管理、系统设置 |
| `ai/` | 模型训练环境与产物 | `ai/.venv` 训练环境、`ai/runs/` 训练输出（不入库） |
| `scripts/` | 辅助脚本 | VOC 转 YOLO、数据体检、训练入口、演示视频生成 |
| `docs/课程任务/` | 课程交付材料 | 分工、项目介绍、参考材料、数据报告，见下方索引 |
| `docs/superpowers/` | 设计与实施文档 | 系统设计文档、各阶段实施计划 |
| `docs/ai-training-records.md` | 模型训练记录 | 数据集、超参、指标与遗留问题 |
| `软件项目管理课程文档/` | 老师提供的资料 | 课程说明、参考模板、需求分析案例 |
| `提交文档/` | 对外提交与分发材料 | 组员写作材料包、课程模板（本地文件，不入库） |
| `datasets/`、`storage/`、`weights/`、`runs/` | 数据与运行产物 | 体积大，已加入 .gitignore，不入库 |

## 快速开始

### 1. 后端（检测服务）

```powershell
ai\.venv\Scripts\python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

- 模型默认路径：`ai/runs/fire26n/weights/best.pt`
- 接口文档：http://127.0.0.1:8000/docs
- 主要接口：`/api/health`、`/api/cameras`、`/api/uploads`、`/api/alarms`、`/api/settings`、`/api/dashboard`、`/stream/{id}`、`/ws/events`

### 2. 前端（监控页面）

```powershell
cd frontend
npm install
npm run dev
```

浏览器访问 http://localhost:5173 （开发期已配置代理到后端 8000 端口）。

### 3. 模型训练与数据

```powershell
ai\.venv\Scripts\python scripts\inspect_voc.py       # 数据集类别统计
ai\.venv\Scripts\python scripts\voc2yolo.py          # VOC 转 YOLO 格式
ai\.venv\Scripts\python scripts\train_yolo.py        # 启动训练（默认 YOLO26n）
```

## 课程交付物索引

| 任务 | 交付物 | 位置 |
| --- | --- | --- |
| 任务1 | 软件介绍（项目简介） | `docs/课程任务/任务1-软件介绍/` |
| 任务2 | 项目章程 | `docs/课程任务/任务2-项目章程/`（docx + md 两种格式） |
| 任务3 | 需求规格说明书（非功能性需求部分已完成，功能需求等章节待合并） | `docs/课程任务/任务3-需求规格说明书/`（docx + md 两种格式） |
| 任务4 | 工作任务分解说明书（含 WBS 树状图与 Project 截图） | 文字部分：`工作任务分解模式与分解库.md`；工作包 Word 表格：`工作任务分解库（工作包明细表）.docx`；配套 Project 任务清单 md/csv 与 项目任务分解.mpp |
| 支撑材料 | 分工与过程记录、统一参考材料、图表说明、数据集说明、数据质量报告 | `docs/课程任务/` |
| 组员材料包 | 打包分发给组员 | `提交文档/组员写作材料包_v1.4.zip`（本地） |

## 协作方式

1. 组员加入 GitHub 仓库后，按"分支 + Pull Request"提交，`master` 只由组长合并；
2. 提交信息格式：`类型(任务N): 说明 - 姓名`；
3. 详见 `docs/课程任务/项目参考材料/Git协作与仓库使用说明（组员版）.docx`；
4. 禁止提交数据集、模型权重、依赖目录与密钥（已在 `.gitignore` 中限制）。

## 数据与声明

- 训练数据来自开源项目 gengyanlei/fire-smoke-detect-yolov4，作者声明仅限学术探索；
- 数据集体检发现重复、低分辨率与近景偏多等问题，详见 `docs/课程任务/数据集质量报告/`；
- 数据集与模型权重不随仓库分发，如需测试请联系组长获取。
