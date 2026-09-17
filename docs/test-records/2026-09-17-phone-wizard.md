# 2026-09-17 手机接入向导开发与验证记录

## 本次范围

为「手机摄像头推流」增加一条可自助完成的接入路径：手机端 IP Webcam 推流 → 电脑端向导填写地址 → 试连成功 → 保存为视频源 → 实时监控页出画。

新增内容：

- 后端：`GET /api/network`（列出本机局域网地址与推荐项）、`POST /api/probe`（试连视频源并返回画面尺寸）；
- 后端：`backend/app/sources.py` 统一封装视频源打开逻辑，网络源带连接/读取超时；
- 前端：`手机接入向导` 页面（`/#/phone`），四步流程 + 常见问题折叠面板。

## 环境

- 后端：`FIREGUARD_DEVICE=0`，`uvicorn backend.app.main:app --host 0.0.0.0 --port 8000`（GPU 推理）
- 前端：`npm run dev`，http://localhost:5173
- 模拟手机端：本机跑一个 IP Webcam 风格的 MJPEG 服务（端口 8080，路径 `/video`，源为演示视频 `demo_fire.mp4`）

## 验证结果

| 检查项 | 命令 / 操作 | 结果 |
| --- | --- | --- |
| 后端用例 | `ai\.venv\Scripts\python -m pytest backend/tests -q` | 6 passed |
| 前端构建 | `npm run build` | 通过（产物含 `PhoneWizardView`） |
| 局域网址接口 | `GET /api/network` | 只返回有效网卡，过滤 `127.*` 与 `169.254.*`，给出推荐地址 |
| 试连成功 | `POST /api/probe` 指向 `http://127.0.0.1:8080/video` | `ok=true`，画面 490×366 |
| 试连超时 | `POST /api/probe` 指向 `http://10.255.255.1:8080/video` | 8.1 秒返回「连接超时」，不再无限阻塞 |
| 地址自动补全 | 向导中只填 `127.0.0.1:8080` | 自动补成 `http://127.0.0.1:8080/video` 并探测成功 |
| 本地视频试连 | 向导中填本地 mp4 路径 | 原样探测成功，且不会误加 `http://` 前缀 |
| 保存为视频源 | 向导点「保存为视频源」 | 新摄像头在线，`/stream/2?annotated=false` 返回真实帧（490×366） |
| 页面渲染 | 无头浏览器抓取 DOM / 控制台 | 无 JS 报错、无横向溢出，菜单与四步卡片均正常 |

## 本次修复的问题

1. `psutil` 被 `/api/network` 使用但未写入 `backend/requirements.txt`，已补 `psutil>=5.9`；
2. OpenCV 的 `CAP_PROP_OPEN_TIMEOUT_MSEC` / `CAP_PROP_READ_TIMEOUT_MSEC` 必须在 `open()` 之前设置才生效，原写法无效，网络源断流时会长时间卡住线程；
3. 向导把任意非 `http/rtsp` 输入都补 `http://`，导致本地文件路径被拼成 `http://E:/...`；已区分本地路径与主机地址，并在只填「主机:端口」时补 `/video`；
4. 网络类视频源的断线重连间隔最长 60 秒，与页面说明不符，已改为最长 10 秒（RTSP / HTTP），本地文件保持 60 秒。

## 遗留事项

1. 需在真实安卓手机 + IP Webcam 上实测一次（本机模拟服务已验证协议链路）；
2. 演示前建议重置告警库，避免历史告警干扰展示；
3. 智能体复核（VLM）与远距离小目标识别仍待开发。
