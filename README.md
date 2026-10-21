# 火情智能监测与预警系统（FireGuard AI）

软件项目管理课程小组实训项目。系统接入手机摄像头、本地上传视频与 RTSP 摄像头，利用自训练深度学习模型实时识别火焰与烟雾，提供分级预警、历史告警、统计分析与系统配置功能。

- 团队：蔡俊杰（组长）、李汶航、欧阳宇康、陈泽恩
- 周期：2026-09-03 ~ 2026-11-05（8 周）
- 仓库：https://github.com/Sanguine668/Fire-Monitoring-System

## 目录结构

| 目录 | 内容 | 说明 |
| --- | --- | --- |
| `backend/` | FastAPI 后端 | 视频源管理、检测 worker、告警引擎、REST/WebSocket/MJPEG 接口 |
| `frontend/` | Vue3 前端 | 监控总览、实时监控、手机接入向导、告警中心、视频源管理、系统设置 |
| `ai/` | 模型训练环境与产物 | `ai/.venv` 训练环境、`ai/runs/` 训练输出（不入库） |
| `scripts/` | 辅助脚本 | 数据管线、预缩放、双类训练、召回/切片评测、演示视频、手机推流模拟 |
| `docs/课程任务/` | 课程交付材料 | 分工、项目介绍、参考材料、数据报告，见下方索引 |
| `docs/superpowers/` | 设计与实施文档 | 系统设计文档、各阶段实施计划 |
| `docs/ai-training-records.md` | 模型训练记录 | 数据集、超参、指标与遗留问题 |
| `docs/demo-checklist.md` | 演示清单 | 启动、手机推流、演示顺序与回退方案 |
| `docs/multi-agent-architecture.md` | 多智能体架构 | 感知/远场/时序/复核/决策五 Agent 的职责、证据与指标 |
| `软件项目管理课程文档/` | 老师提供的资料 | 课程说明、参考模板、需求分析案例 |
| `提交文档/` | 本地课程模板 | 学校实验报告封面模板、项目章程参考模板（不进仓库） |
| `datasets/`、`storage/`、`weights/`、`runs/` | 数据与运行产物 | 体积大，已加入 .gitignore，不入库 |

## 快速开始

### 1. 后端（检测服务）

```powershell
$env:FIREGUARD_DEVICE = '0'   # 用第 0 号 GPU 推理；不设则自动判断
ai\.venv\Scripts\python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

- `--host 0.0.0.0` 是手机接入的前提，否则手机访问不到电脑；
- 模型默认路径：`ai/runs/fire26n-v2/weights/best.pt`（20 轮 D-Fire 双类模型）
- 接口文档：http://127.0.0.1:8000/docs
- 主要接口：`/api/health`、`/api/network`、`/api/probe`、`/api/cameras`、`/api/uploads`、`/api/alarms`、`/api/settings`、`/api/dashboard`、`/stream/{id}`、`/ws/events`
- 注意：本机 CPU 推理会因线程/内存限制报错，演示与调试请使用 GPU（`FIREGUARD_DEVICE=0`）

### 2. 前端（监控页面）

```powershell
cd frontend
npm install
npm run dev
```

浏览器访问 http://localhost:5173 （开发期已配置代理到后端 8000 端口）。

### 3. 手机摄像头接入（IP Webcam）

页面入口：左侧菜单「手机接入向导」（http://localhost:5173/#/phone），四步走完即可：

1. 网络准备：手机开热点 → 电脑连入该热点（或两者连同一 WiFi），页面会列出本机可用的局域网地址并标出推荐项；
2. 手机端：安装 IP Webcam → 分辨率建议 640×480、格式 MJPEG → 滑到底部点 `Start server`；
3. 填写地址：只填 `192.168.43.1` 会自动补成 `http://192.168.43.1:8080/video`，点「测试连接」确认能取到画面；
4. 保存为视频源：进入「实时监控」即可看到手机画面与检测框。

如果 `/video` 连不上，点「自动检测可用地址」，系统会依次尝试 `/video`、`/videofeed`、`/shot.jpg` 和 IP Webcam 的 RTSP 端点；`/shot.jpg` 会以快照轮询方式接入。

常见问题：探测超时通常是手机没点 `Start server`，或电脑连的不是手机热点；添加后显示离线时系统会自动重连（2 秒起、最长 10 秒）。

手边没有安卓手机时，可以先用脚本在本机模拟一路 IP Webcam 推流（读取 `storage/uploads/` 下的演示视频）：

```powershell
ai\.venv\Scripts\python scripts\mock_phone_cam.py
```

然后在向导第 3 步填 `127.0.0.1:8080`，即可走完探测、保存、出画的完整流程。

### 4. 模型训练与数据

```powershell
ai\.venv\Scripts\python scripts\prepare_dfire.py          # 生成 D-Fire 双类数据列表与远景/负样本评测集
ai\.venv\Scripts\python scripts\build_resized_dataset.py   # 预缩放到长边 640，加快单进程训练
ai\.venv\Scripts\python scripts\train_yolo_v2.py --data datasets/fire-smoke-v2-640/data.yaml --epochs 20 --batch 8 --workers 0
```

Windows 下 DataLoader 多进程会因页文件不足触发 `WinError 1455`，训练统一使用 `--workers 0`；预缩放数据集用于降低每轮解码耗时。

### 5. 远距离识别与告警复核

- 远距离模式：每 2 秒把整帧切成 640 瓦片（20% 重叠）做一次高分辨率扫描，跨片 NMS 合并；其余帧仍走整图推理，兼顾帧率与远景小目标召回；
- 告警复核：触发告警时放大局部区域做二次检测，复核不通过则抑制本次告警，降低单帧误报；
- 两项参数都在「系统设置」页调整，监控页会在切片帧上显示「远距离扫描」标记；
- 演示视频：`storage/uploads/demo_farfield.mp4`，由 `scripts/make_farfield_demo.py` 从 D-Fire 连续远景帧生成。

## 课程交付物索引

| 任务 | 交付物 | 位置 |
| --- | --- | --- |
| 任务1 | 软件介绍（项目简介） | `docs/课程任务/暂时定稿的文档/项目介绍.docx` |
| 任务2 | 项目章程 | `docs/课程任务/暂时定稿的文档/项目章程.docx` |
| 任务3 | 需求规格说明书（含功能性需求 UC-01~UC-16、非功能性需求、附录 A 需求调查） | `docs/课程任务/暂时定稿的文档/需求规格说明书.docx` |
| 任务4 | 工作任务分解说明书（含 WBS 树状图与 Project 甘特图） | `docs/课程任务/暂时定稿的文档/工作任务分解说明书.docx`；Project 工程与计划清单：`docs/课程任务/任务4-工作任务分解说明书/` |
| 支撑材料 | 分工与过程记录、统一参考材料、图表说明、数据集说明、数据质量报告 | `docs/课程任务/` |
| 实验5~11 | **组员任务清单**（提交文档、要求与流程、分工、每人负责的章节） | `docs/课程任务/实验5-11任务清单（组员版）.md` |
| 实验5~11 | 写作依据（七份参考目录，含建议章节、必写项、去重说明） | `往期作业参考/项目XX管理相关文档/` |
| 实验5~11 | 实验说明与产出清单（早期版本，分工部分已由任务清单取代） | `docs/课程任务/实验5-11说明与分工.md` |
| 项目现状 | 项目介绍、模块状态、里程碑、数据与模型现状（更新至 2026-10-08） | `docs/课程任务/项目介绍与任务分工.md` |
| 课程模板 | 学校实验报告封面模板、项目章程参考模板 | `提交文档/课程模板/`（本地） |

## 协作方式

1. 组员加入 GitHub 仓库后，按"分支 + Pull Request"提交，`master` 只由组长合并；
2. 提交信息格式：`类型(任务N): 说明 - 姓名`；
3. 详见 `docs/课程任务/项目参考材料/Git协作与仓库使用说明（组员版）.docx`；
4. 禁止提交数据集、模型权重、依赖目录与密钥（已在 `.gitignore` 中限制）。

## 数据与声明

- 当前训练集为 D-Fire（CC0，21,527 张，fire/smoke 双类，含 9,838 张负样本）；
- 组员补充数据集的取舍见 `docs/课程任务/数据集候选/新增数据集评估_20261020.md`；
- 数据集与模型权重不随仓库分发，如需测试请联系组长获取。
