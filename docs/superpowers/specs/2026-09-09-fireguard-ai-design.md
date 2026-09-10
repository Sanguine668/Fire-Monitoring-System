# FireGuard AI · 火灾智能监测与预警系统 —— 设计文档

- 课程：软件项目管理 · 小组实训
- 文档版本：v1.0（设计确认版）
- 日期：2026-09-09
- 关联文档：《项目介绍与任务分工.md》（docs/课程任务/，v0.4，人员角色与分工见该文）

---

## 1. 背景与目标

本项目面向火灾早期监测场景，构建"视频源 → AI 烟火检测 → 分级预警 → 前端展示 → 历史留存"完整闭环。

核心目标：

1. 支持**安卓手机摄像头实时推流**，在局域网内实时识别并展示检测结果（老师重点要求）；
2. 支持**本地上传视频**，作为循环播放的 `file` 型视频源接入同一检测链路，保证演示可控、可复现；
3. 使用**自训练的较新 YOLO 系列模型**完成烟火检测，并与现有开源模型做对比评测；
4. 在约 8 次实训（每次约 3.5 小时）内交付可演示系统 + 完整项目管理文档。

课堂演示不允许使用真实火源；演示素材为烟火视频/图片（屏幕播放或翻拍）与本地上传视频。

---

## 2. 范围

### 2.1 模块分批

| 批次 | 模块 | 验收要点 |
| --- | --- | --- |
| 核心闭环 | 实时监控 | Vue3 页面实时显示画面、检测框、FPS/延迟/风险分 |
| 核心闭环 | 烟火检测 | 自训练 YOLO 模型对视频帧输出 fire/smoke 检测结果 |
| 核心闭环 | 实时预警 | 连续帧 + 阈值 + 冷却规则产生分级告警，经 WebSocket 推送 |
| 核心闭环 | 视频源管理 | 增删/启停视频源；上传本地视频为 file 型源 |
| 核心闭环 | 历史告警 | 告警列表、确认处理、快照（快照延后） |
| 增量增强 | 统计分析 | ECharts 趋势与统计（Dashboard） |
| 增量增强 | 系统配置 | 阈值/连续帧/冷却参数真实作用于告警引擎 |
| 增量增强 | 告警快照 | 告警时刻截图留存（若进度允许） |

### 2.2 非目标（本期不做）

- 不引入 PostgreSQL、Docker、Kubernetes；
- MVP 阶段不部署 MediaMTX（保留为演进项）；
- 不做 WebRTC 亚秒级低延迟传输（MJPEG 已满足演示）；
- 不承诺移动端 App（手机仅作为视频源）。

---

## 3. 总体架构与部署形态

MVP 全部运行在一台 Windows 笔记本（含 NVIDIA GPU）上，单个 FastAPI 进程承载 REST API、WebSocket、静态前端托管与检测 worker。

```text
视频源层
  ├─ file：storage/uploads 下的 MP4（循环播放）
  └─ rtsp/http：安卓 IP Webcam / 后续真实摄像头
          ↓
检测 worker（每路启用源一个后台任务）
  ├─ OpenCV 取帧（3~5 FPS 采样）
  ├─ DetectorAdapter.detect(frame) → YOLO 推理
  ├─ 绘制检测框 → 最新 JPEG → MJPEG 流
  └─ 结果送入告警规则引擎
          ↓
告警规则引擎（每路独立状态机）
          ↓
SQLite（cameras / alarms / settings）+ WebSocket 事件推送
          ↓
Vue3 + Element Plus + ECharts 前端
```

### 3.1 技术栈

| 层 | 选型 | 备注 |
| --- | --- | --- |
| 前端 | Vue3 + Vite + Element Plus + ECharts | 开发期 Vite dev server；演示期构建产物由 FastAPI 托管 |
| 后端 | FastAPI + WebSocket + SQLite | 沿用 demo 的 REST/WS 消息契约并扩展 |
| 视频 | OpenCV (cv2.VideoCapture) | file 直读；手机 http/rtsp 直连；MediaMTX 演进项 |
| AI | Python + Ultralytics（自训练 YOLO） | CUDA 推理；提供 CPU fallback 配置 |
| 模型对比 | D-Fire YOLOv8n / gengyanlei yolov5 best.pt / Pyronear | 对比用基线，不自训 |

### 3.2 开发与演示环境约定

- 代码统一进 Git 仓库，成员各自机器上开发；每周实训合并、联调；
- 演示机固定为蔡俊杰 的 NVIDIA 笔记本；AI 训练、后端与演示构建在该机完成；
- FastAPI 启动监听 `0.0.0.0`，Windows 防火墙放行所需端口；
- 手机热点演示拓扑：笔记本连接手机热点 → 手机端 IP Webcam 提供画面 → worker 拉取手机地址；
- 前端成员（李汶航）可在自己的机器上用 Vite dev server + mock 数据先行开发，接口以 4.4/4.5 契约为准。

---

## 4. 组件设计与接口契约

### 4.1 视频源抽象

`cameras` 表字段（在 demo 基础上扩展）：

| 字段 | 说明 |
| --- | --- |
| id / name / location / enabled | 沿用 demo |
| source_type | `file` / `rtsp` / `http` |
| source | 文件路径或流地址（如手机 `http://192.168.x.x:8080/video`） |
| online | worker 当前连通状态 |
| loop | file 源是否循环播放（默认 1） |

统一规则：worker 只关心"取到一帧并推理"，不关心源类型。

### 4.2 检测 worker 与 DetectorAdapter

- 每路启用源一个后台任务；启停视频源 = 启停任务；
- `DetectorAdapter.detect(frame)` 返回统一结构：

```json
[
  {"type": "fire", "confidence": 0.91, "bbox": [x, y, w, h]},
  {"type": "smoke", "confidence": 0.78, "bbox": [x, y, w, h]}
]
```

- 采样频率默认 4 FPS（3~5 可配置）；单帧 CPU/GPU 推理时间作为 latency 指标上报。

### 4.3 实时画面上屏（MJPEG）

- 接口：`GET /stream/{camera_id}`，返回 `multipart/x-mixed-replace` 标注帧流；
- 前端 `<img :src="...">` 显示，检测框直接画在帧上；
- 目标延迟 0.3~1 秒，课堂演示可接受；
- 同一路源支持多浏览器标签消费（worker 维护最新 JPEG 帧缓存）。

### 4.4 WebSocket 事件契约（沿用 demo 结构）

- `detection`：`{event, seq, camera_id, timestamp, fps, latency_ms, objects[], risk_score, status}`
- `alarm`：`{event:"alarm", alarm:{...}}`
- `camera_online` / `camera_offline`：视频源状态变更
- 连接/心跳沿用 demo 实现（`connected`、`ping`）。

### 4.5 REST API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | /api/health | 健康检查 |
| GET | /api/cameras | 视频源列表 |
| POST | /api/cameras | 新增 rtsp/http 源 |
| POST | /api/uploads | 上传视频，自动建 file 源 |
| POST | /api/cameras/{id}/toggle | 启用/停用（启停 worker） |
| DELETE | /api/cameras/{id} | 删除源及对应文件（file 源可选删除文件） |
| GET | /stream/{id} | MJPEG 标注帧流 |
| GET | /api/alarms?limit= | 告警列表 |
| POST | /api/alarms/{id}/ack | 确认处理 |
| GET | /api/dashboard | 统计总览 |
| GET/PUT | /api/settings | 读取/保存告警参数 |
| WS | /ws/events | 实时事件通道 |

`/api/demo/trigger/*` 仅在开发环境保留，作为 UI 自测入口，不参与生产判定路径。

### 4.6 数据模型

- `cameras`：见 4.1；
- `alarms`：沿用 demo 字段，预留 `snapshot_path`（快照阶段启用）；
- `settings`：`fire_threshold`（默认 0.1）、`smoke_threshold`（0.1）、`continuous_frames`（3）、`alarm_cooldown`（8），全部真实接入规则引擎；阈值默认值依据首轮模型的置信度校准结果设定（该权重置信度整体偏低，详见 docs/ai-training-records.md），换模型后需重新校准。
- 新增 `model_runs` 表（可选）：记录训练/评测实验（模型名、数据版本、mAP、日期），支撑对比报告。

---

## 5. 告警规则与防误报

每路摄像头独立状态机：

```text
normal ──连续 N 帧 smoke 超阈值──→ 疑似 smoke ──持续超阈值→ yellow 预警
任意帧 fire 超阈值（或 fire+smoke）──→ critical 红色告警
告警落库受冷却时间约束（默认 8s），期间只推送不重复落库
视频源断流/离线 → 状态机复位，防止重连后瞬时误报
```

- 风险分由检测类别与置信度综合计算（fire 权重高于 smoke）；
- 阈值、连续帧、冷却全部来自 `settings` 并可在线修改；
- 负样本回归场景：灯光、蒸汽、屏幕反光、夕阳等（第 5~6 周起）。

---

## 6. 错误处理与稳定性

- 断流重连：指数退避（1s→2s→4s…上限 60s），超过 N 次标记 offline 并推事件；
- 单路 worker 异常只影响该路，主服务不退出，异常记日志；
- file 源播完自动 seek 循环；文件损坏 → 标记该源 offline 并提示；
- 上传约束：MP4/MOV，优先 H.264；默认上限 500MB；同名文件自动加时间戳；
- 手机掉线时系统整体可用，切换到 file 源保底演示。

---

## 7. 前端设计

### 7.1 页面

| 页面 | 核心内容 |
| --- | --- |
| 监控总览 Dashboard | 卡片指标、ECharts 趋势、最近告警 |
| 实时监控 | MJPEG 视频墙 + 检测框 + 风险分 + FPS/延迟 |
| 告警中心 | 告警表格、确认处理、筛选 |
| 视频源管理 | 源列表、启停、新增、上传入口 |
| 系统设置 | 阈值/连续帧/冷却表单 |

### 7.2 约定

- 视觉与交互参考现有 `archive/早期演示系统/FireGuard_AI_Demo_Windows/frontend`（不作为正式代码迁移）；
- 组件化拆分：VideoCard、AlarmTable、CameraDialog、UploadDialog、SettingsForm、ChartPanel；
- 开发期前端调用通过 Vite proxy 指向 FastAPI（默认 8000 端口）；
- 演示构建：`npm run build` → FastAPI 托管 `dist/`，课堂一键启动。

---

## 8. AI 检测与模型训练

### 8.1 训练目标与验收口径

- 采用 **gengyanlei 烟火数据集（VOC2020，JPEGImages 2059 张 + XML 标注）** 自训练较新的 YOLO 模型：Ultralytics 当前稳定版（2026-09 官方文档推荐 YOLO26 系列），**首轮使用 YOLO26n**（适配 6GB 显存、保证第一周跑通）；首轮稳定后可选 YOLO26s/YOLO11s 做精度对比并记录；
- 验收指标：验证集 mAP50、mAP50-95、Precision、Recall、F1，目标 mAP50 ≥ 0.75（数据集标注噪声下允许合理调整目标并记录）；
- 课堂演示口径：对手机翻拍/上传的烟火素材能稳定出框，单帧 GPU 推理延迟可满足 3~5 FPS；
- 与 D-Fire YOLOv8n、gengyanlei yolov5 best.pt（必要时 Pyronear）在同一验证集与演示素材上做对比，产出对比报告。

### 8.2 数据集现状与默认决策

数据集为 Pascal VOC 格式（Annotations XML / JPEGImages / ImageSets），作者声明"本数据仅学术探索"，文档与代码中需记录该声明。

**默认决策**：下载后第一步统计类别分布。

- 若标注含 fire + smoke 两类 → 按两类训练；
- 若仅含 fire 类 → 第一轮先完成 fire 单类训练并记录；smoke 检测在自训模型补入烟类数据前，由基线模型（D-Fire/gengyanlei）兜底；烟类数据扩充（同仓库 yolov5 模型伪标注 + 人工修正，或下载 10827 张烟火数据集）作为第二轮训练任务，不阻塞第 1~2 周主线。

数据集存放路径：`datasets/fire-smoke-voc/`（需组员从百度网盘链接下载后放入，压缩包解压两次的场景按仓库说明处理）。

### 8.3 训练管线

1. VOC XML → YOLO txt（脚本 `scripts/voc2yolo.py`），类别顺序固定并写入 `data.yaml`；
2. 划分训练/验证（建议 85/15，固定随机种子保证可复现）；
3. `data.yaml`：path/nc/names；图像尺寸 640；epochs 100 + early stop；
4. 训练后导出/保存 best.pt，记录每轮实验（数据集版本、超参、指标）到 `model_runs` 或实验记录表；
5. 评测：自动指标 + 指定演示素材定性截图。

### 8.4 风险与兜底

| 风险 | 应对 |
| --- | --- |
| 数据集只有 fire 标注 | 烟类先用基线模型兜底；后续引入烟类数据训练（见 8.2） |
| 标注质量/类别不平衡影响 mAP | 训练中检查类别分布；指标目标按实测调整并记录依据 |
| 百度网盘下载受阻 | 优先组员手动下载；必要时查找同源镜像（Kaggle/HF），记录数据来源与版本 |
| 显存不足 | 按 8.1 自适应降尺寸/batch；必要时减小输入分辨率至 480 |
| 训练占用开发机影响其他工作 | 训练跑后台任务，前端/后端在另一台或错峰使用；早停控制时长 |

---

## 9. 测试策略

- 单元：告警状态机（连续帧/阈值/冷却）用伪造检测流测试；
- 接口：REST 增删改查 + 上传；WebSocket 事件可达性；
- 集成：本地 file 源端到端（上传 → 画面 → 告警 → 历史）；
- 回归：demo 触发按钮（UI 自测模式）、设置参数修改后规则生效；
- 现场：手机热点推流全链路预演；断网/掉线场景验证保底通道；
- 文档配套：测试用例表、测试记录、缺陷清单（C 负责）。

---

## 10. 演示与验收

最终演示（约 10~15 分钟）固定脚本：

1. 系统总览与架构说明（文档 + 页面）；
2. 本地上传烟火视频 → 实时识别 + 分级告警 + 历史记录（保底通道）；
3. 手机热点推流 → 手机画面实时识别（老师重点要求，提前预演）；
4. 统计页面与设置演示；
5. 展示自训模型与基线模型对比表。

---

## 11. 里程碑与并行工作线

| 周次 | AI/后端线（蔡俊杰主责，欧阳宇康、陈泽恩协助） | 前端线（李汶航主责） |
| --- | --- | --- |
| 第 1 周 | 环境（CUDA/PyTorch/Ultralytics）；数据集下载与类别统计；模型冒烟推理 | Vue3 脚手架 + 基础页面骨架（监控/告警/视频源/设置） |
| 第 2~3 周 | 数据转换与自训练启动；检测 worker + MJPEG + 告警引擎；上传接口 | 实时监控页（画面/检测框/风险 UI）、上传入口联调 |
| 第 4 周 | 手机 http/rtsp 源接入；参数真实生效 | 视频源管理完整交互、状态展示 |
| 第 5~6 周 | 第二轮训练（烟类扩充/负样本）；快照留存 | 统计图表 ECharts、告警中心完善 |
| 第 7~8 周 | 模型对比报告、推理优化 | 页面打磨、演示构建脚本 |

双线互不阻塞：前端以固定接口契约为准开发，可先用 demo 数据源/模拟接口联调。

---

## 12. 风险登记（摘要）

| 风险 | 概率 | 影响 | 应对 |
| --- | --- | --- | --- |
| 训练数据只有 fire 类 | 高 | 烟检测缺自训能力 | 基线模型兜底 + 烟类数据第二轮 |
| 翻拍屏幕检出率低 | 中 | 演示效果差 | 冒烟期用课堂同款素材验证，准备多套素材 |
| 每周有效时间不足 | 高 | 进度延迟 | 核心闭环优先、每周可演示、砍后置项 |
| 手机热点/推流不稳定 | 中 | 重点功能演示失败 | file 源保底 + 演示前预演 |
| 模板/文档返工 | 中 | 时间浪费 | 模板发布后第一周对齐 |

---

## 13. 参考链接

- 数据集与 yolov4/yolov5 参考：[gengyanlei/fire-smoke-detect-yolov4 README_ZN](https://github.com/gengyanlei/fire-smoke-detect-yolov4/blob/master/readmes/README_ZN.md)
- MediaMTX（演进项）：https://github.com/bluenviron/mediamtx
- 基线模型候选：D-Fire YOLOv8n（HuggingFace rabahdev/fire-smoke-yolov8n）、Pyronear 早烟模型
