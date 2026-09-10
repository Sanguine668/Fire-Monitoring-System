# 2026-09-10 前后端联调记录

## 联调范围

前端 Vue3 页面与后端 FastAPI 检测服务的真实数据对接：总览统计、实时画面（MJPEG）、告警列表与确认、视频源管理与上传、系统参数读写、WebSocket 事件。

## 环境

- 后端：`ai\.venv\Scripts\python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000`（CPU 推理）
- 前端：`npm run dev`，地址 http://localhost:5173
- 视频源：已上传演示视频 `demo_fire.mp4`（file 型，循环播放）

## 验证结果

| 检查项 | 命令 / 操作 | 结果 |
| --- | --- | --- |
| 前端构建 | `npm run build` | 通过 |
| 代理健康检查 | `curl http://localhost:5173/api/health` | 200，返回服务状态 |
| 视频源列表 | `curl http://localhost:5173/api/cameras` | 返回 demo_fire，online=1 |
| 告警列表 | `curl http://localhost:5173/api/alarms?limit=2` | 返回 fire/critical 告警记录 |
| 实时画面 | `curl -N --max-time 4 http://localhost:5173/stream/2` | 4 秒收到约 1.19MB MJPEG 数据 |
| 后端托管前端 | `curl http://127.0.0.1:8000/` | 200 text/html，返回前端页面 |

## 结论

前后端链路打通：监控页可显示真实检测画面，告警、视频源与设置页均使用后端真实数据。剩余待办：

1. 手机 IP Webcam 推流联调（需在局域网/手机热点环境实测）；
2. 演示数据库清理（当前累积大量历史告警，演示前可重置）；
3. 告警截图留存与统计图表增强。
