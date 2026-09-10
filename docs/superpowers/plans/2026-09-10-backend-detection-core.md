# 后端检测核心闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在仓库根目录新建 `backend/` FastAPI 应用，把真实 YOLO 模型接成检测 worker，支持"本地上传视频源 + 摄像头源 → 抽帧推理 → 告警状态机 → SQLite + WebSocket + MJPEG"，使前端实时监控页可以显示真实检测画面。

**Architecture:** FastAPI 单进程承载 REST/WebSocket/静态前端；每路启用视频源一个 `threading.Thread` worker；worker 读取帧 → `YoloDetector.detect()` → `AlarmEngine` 状态机 → 落库 + WS 推送 + 最新标注 JPEG 缓存；`/stream/{id}` 以 MJPEG 输出缓存帧；SQLite 沿用 demo 表结构并扩展 `source_type/source/loop`。

**Tech Stack:** FastAPI、uvicorn、Python 3.12 venv（ai/.venv，含 CUDA torch + Ultralytics）、OpenCV、SQLite、WebSocket、multipart 上传。

## Global Constraints

- 运行解释器：`ai\.venv\Scripts\python`（含 GPU torch、ultralytics 8.4.145）；需追加安装 fastapi、uvicorn[standard]、python-multipart、pytest。
- 模型权重默认路径：`ai/runs/fire26n/weights/best.pt`（缺失时启动报错并提示先训练）；可用环境变量 `FIREGUARD_MODEL` 覆盖。
- 数据库默认路径：`storage/fireguard.db`；可用环境变量 `FIREGUARD_DB` 覆盖（供测试）。
- 视频源字段：`source_type` ∈ {`file`,`rtsp`,`http`}；`file` 源播完自动循环。
- 检测消息结构保持 demo 契约：detection/alarm/camera_online/camera_offline。
- 每路源一个后台 worker；toggle = 启停 worker；上传视频自动建 `file` 源并启动 worker。
- 预览页开发不依赖 Vue 构建：接口全部可用 curl 验证；前端接入放下一份计划。

## File Structure

```
backend/
├─ requirements.txt
├─ app/
│  ├─ __init__.py
│  ├─ config.py        # 路径与模型/DB 常量
│  ├─ db.py            # SQLite 连接与 CRUD
│  ├─ events.py        # WebSocket manager
│  ├─ detector.py      # YoloDetector（detect(frame) 接口）
│  ├─ alarm_engine.py  # 纯状态机：连续帧/阈值/冷却
│  ├─ worker.py        # DetectionWorker 线程
│  ├─ main.py          # FastAPI 应用、lifespan、REST/WS/MJPEG
│  └─ static.py        # 托管 frontend/dist（若有）
├─ tests/
│  ├─ test_alarm_engine.py
│  └─ test_api.py
```

---

### Task 1: 依赖、目录、配置与数据库

**Files:**
- Create: `backend/requirements.txt`、`backend/app/__init__.py`、`backend/app/config.py`、`backend/app/db.py`
- Test: pytest 空跑 + 数据库初始化单测

**Interfaces:**
- Consumes: ai/.venv 环境。
- Produces: `config.ROOT/STORAGE/DB_PATH/MODEL_PATH`；`db.init_db()`；`db` CRUD 函数供后续任务使用。

- [ ] **Step 1: 安装后端依赖到 ai venv**

```powershell
ai\.venv\Scripts\python -m pip install fastapi "uvicorn[standard]" python-multipart pytest -i https://pypi.tuna.tsinghua.edu.cn/simple --timeout 60
```

预期：安装成功。

- [ ] **Step 2: 写入依赖文件**

`backend/requirements.txt`：

```txt
fastapi>=0.115,<1.0
uvicorn[standard]>=0.30,<1.0
python-multipart>=0.0.9
opencv-python>=4.8
ultralytics>=8.4
torch>=2.0
```

- [ ] **Step 3: 写入 config.py**

```python
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STORAGE = ROOT / "storage"
UPLOADS = STORAGE / "uploads"
SNAPSHOTS = STORAGE / "snapshots"
FRONTEND_DIST = ROOT / "frontend" / "dist"

DB_PATH = Path(os.environ.get("FIREGUARD_DB", str(STORAGE / "fireguard.db")))
MODEL_PATH = Path(os.environ.get("FIREGUARD_MODEL", str(ROOT / "ai" / "runs" / "fire26n" / "weights" / "best.pt")))
FRAME_QUALITY = int(os.environ.get("FIREGUARD_FRAME_QUALITY", "80"))
DEFAULT_FPS = 4.0
```

- [ ] **Step 4: 写入 db.py**

```python
from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from .config import DB_PATH


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS cameras (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                location TEXT NOT NULL DEFAULT '',
                source_type TEXT NOT NULL,
                source TEXT NOT NULL,
                loop INTEGER NOT NULL DEFAULT 1,
                online INTEGER NOT NULL DEFAULT 0,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS alarms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                camera_id INTEGER NOT NULL,
                camera_name TEXT NOT NULL,
                alarm_type TEXT NOT NULL,
                level TEXT NOT NULL,
                confidence REAL NOT NULL,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'unhandled'
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        for k, v in {
            "fire_threshold": "0.5",
            "smoke_threshold": "0.5",
            "continuous_frames": "3",
            "alarm_cooldown": "8",
        }.items():
            c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))


def insert_camera(name: str, source_type: str, source: str, location: str = "", loop: int = 1) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO cameras(name,location,source_type,source,loop,online,enabled,created_at)"
            " VALUES(?,?,?,?,?,0,1,?)",
            (name, location, source_type, source, loop, now_text()),
        )
        return int(cur.lastrowid)


def list_cameras() -> list[dict[str, Any]]:
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM cameras ORDER BY id").fetchall()]


def get_camera(camera_id: int) -> dict[str, Any] | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM cameras WHERE id=?", (camera_id,)).fetchone()
        return dict(row) if row else None


def set_camera_enabled(camera_id: int, enabled: bool) -> None:
    with _conn() as c:
        c.execute("UPDATE cameras SET enabled=? WHERE id=?", (1 if enabled else 0, camera_id))


def set_camera_online(camera_id: int, online: bool) -> None:
    with _conn() as c:
        c.execute("UPDATE cameras SET online=? WHERE id=?", (1 if online else 0, camera_id))


def delete_camera(camera_id: int) -> None:
    with _conn() as c:
        c.execute("DELETE FROM cameras WHERE id=?", (camera_id,))


def create_alarm(camera_id: int, camera_name: str, alarm_type: str, level: str, confidence: float) -> dict[str, Any]:
    with _conn() as c:
        created = now_text()
        cur = c.execute(
            "INSERT INTO alarms(camera_id,camera_name,alarm_type,level,confidence,created_at,status)"
            " VALUES(?,?,?,?,?,?,'unhandled')",
            (camera_id, camera_name, alarm_type, level, confidence, created),
        )
        return {
            "id": int(cur.lastrowid),
            "camera_id": camera_id,
            "camera_name": camera_name,
            "alarm_type": alarm_type,
            "level": level,
            "confidence": round(confidence, 3),
            "created_at": created,
            "status": "unhandled",
        }


def list_alarms(limit: int = 100) -> list[dict[str, Any]]:
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM alarms ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]


def ack_alarm(alarm_id: int) -> bool:
    with _conn() as c:
        cur = c.execute("UPDATE alarms SET status='handled' WHERE id=? AND status='unhandled'", (alarm_id,))
        return cur.rowcount > 0


def get_settings() -> dict[str, float | int]:
    with _conn() as c:
        values = {r["key"]: r["value"] for r in c.execute("SELECT * FROM settings").fetchall()}
    return {
        "fire_threshold": float(values["fire_threshold"]),
        "smoke_threshold": float(values["smoke_threshold"]),
        "continuous_frames": int(values["continuous_frames"]),
        "alarm_cooldown": int(values["alarm_cooldown"]),
    }


def put_settings(values: dict[str, float | int]) -> dict[str, float | int]:
    with _conn() as c:
        for k, v in values.items():
            c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (k, str(v)))
    return {k: v for k, v in values.items()}


def dashboard_stats() -> dict[str, Any]:
    with _conn() as c:
        camera_count = c.execute("SELECT COUNT(*) n FROM cameras").fetchone()["n"]
        online_count = c.execute("SELECT COUNT(*) n FROM cameras WHERE online=1").fetchone()["n"]
        today = datetime.now().strftime("%Y-%m-%d") + "%"
        alarm_count = c.execute("SELECT COUNT(*) n FROM alarms WHERE created_at LIKE ?", (today,)).fetchone()["n"]
        unhandled = c.execute("SELECT COUNT(*) n FROM alarms WHERE status='unhandled'").fetchone()["n"]
        recent = [dict(r) for r in c.execute("SELECT * FROM alarms ORDER BY id DESC LIMIT 5").fetchall()]
    return {
        "camera_count": camera_count,
        "online_count": online_count,
        "today_alarms": alarm_count,
        "unhandled": unhandled,
        "recent": recent,
    }
```

- [ ] **Step 5: 初始化目录、conftest 与最小测试**

创建 `backend/tests/conftest.py`：

```python
import os
import tempfile
from pathlib import Path

tmp = tempfile.mkdtemp(prefix="fireguard-test-")
os.environ["FIREGUARD_DB"] = str(Path(tmp) / "test.db")
```

创建 `backend/tests/test_db.py`：

```python
from backend.app import db  # noqa: E402


def test_init_and_crud() -> None:
    db.init_db()
    cid = db.insert_camera("测试源", "file", "C:/tmp/demo.mp4")
    assert db.get_camera(cid)["name"] == "测试源"
    db.set_camera_online(cid, True)
    assert db.get_camera(cid)["online"] == 1
    assert db.get_settings()["fire_threshold"] == 0.5
    db.delete_camera(cid)
```

在 `backend/tests/__init__.py` 与 `backend/__init__.py` 各放空文件；然后运行：

```powershell
ai\.venv\Scripts\python -m pytest backend/tests -q
```

预期：1 passed。

- [ ] **Step 6: 提交**

```bash
git add backend
git commit -m "feat(backend): 应用骨架、配置与 SQLite 数据层"
```

---

### Task 2: 告警状态机（纯逻辑 + 测试）

**Files:**
- Create: `backend/app/alarm_engine.py`、`backend/tests/test_alarm_engine.py`

**Interfaces:**
- Consumes: 无。
- Produces: `AlarmEngine.reset()`、`AlarmEngine.update(now, detections, fire_threshold, smoke_threshold, continuous_frames, cooldown_s) -> (status, risk, alarm|None)`，其中 `alarm` 为 `{alarm_type, level, confidence}` 或 None。

- [ ] **Step 1: 写失败测试**

`backend/tests/test_alarm_engine.py`：

```python
from backend.app.alarm_engine import AlarmEngine


def smoke(detections, n=3, conf=0.7, step=0.3, start=100.0):
    engine = AlarmEngine()
    last = None
    for i in range(n):
        _, _, alarm = engine.update(start + i * step, detections, 0.5, 0.5, 3, 8)
        last = alarm
    return engine, last


def test_smoke_warning_after_continuous_frames() -> None:
    engine, alarm = smoke([{"type": "smoke", "confidence": 0.7, "bbox": [0, 0, 1, 1]}])
    assert alarm is not None and alarm["alarm_type"] == "smoke" and alarm["level"] == "warning"
    # 冷却期内不重复告警
    _, _, alarm2 = engine.update(101.0, [{"type": "smoke", "confidence": 0.7, "bbox": [0, 0, 1, 1]}], 0.5, 0.5, 3, 8)
    assert alarm2 is None


def test_fire_critical_immediate() -> None:
    engine = AlarmEngine()
    _, _, alarm = engine.update(1.0, [{"type": "fire", "confidence": 0.9, "bbox": [0, 0, 1, 1]}], 0.5, 0.5, 3, 8)
    assert alarm is not None and alarm["level"] == "critical"


def test_low_confidence_ignored() -> None:
    engine = AlarmEngine()
    _, _, alarm = engine.update(1.0, [{"type": "fire", "confidence": 0.1, "bbox": [0, 0, 1, 1]}], 0.5, 0.5, 3, 8)
    assert alarm is None
```

运行 `ai\.venv\Scripts\python -m pytest backend/tests/test_alarm_engine.py -q`，预期 FAIL（模块不存在）。

- [ ] **Step 2: 实现状态机**

`backend/app/alarm_engine.py`：

```python
from __future__ import annotations

from typing import Any


class AlarmEngine:
    """每路视频源独立的告警状态机（纯逻辑，便于单测）。"""

    def __init__(self) -> None:
        self.smoke_streak = 0
        self.last_alarm_ts = -1e9
        self.risk = 0
        self.status = "normal"

    def reset(self) -> None:
        self.smoke_streak = 0
        self.last_alarm_ts = -1e9
        self.risk = 0
        self.status = "normal"

    def update(
        self,
        now: float,
        detections: list[dict[str, Any]],
        fire_threshold: float,
        smoke_threshold: float,
        continuous_frames: int,
        cooldown_s: float,
    ) -> tuple[str, int, dict[str, Any] | None]:
        fire_conf = max(
            (d["confidence"] for d in detections if d["type"] == "fire" and d["confidence"] >= fire_threshold),
            default=0.0,
        )
        smoke_conf = max(
            (d["confidence"] for d in detections if d["type"] == "smoke" and d["confidence"] >= smoke_threshold),
            default=0.0,
        )
        alarm = None

        if fire_conf > 0:
            self.smoke_streak = 0
            self.status = "critical"
            self.risk = min(99, 80 + round(fire_conf * 15))
            if now - self.last_alarm_ts >= cooldown_s:
                alarm = {"alarm_type": "fire", "level": "critical", "confidence": fire_conf}
                self.last_alarm_ts = now
        elif smoke_conf > 0:
            self.smoke_streak += 1
            if self.smoke_streak >= continuous_frames:
                self.status = "warning"
                self.risk = min(80, 45 + round(smoke_conf * 25))
                if now - self.last_alarm_ts >= cooldown_s:
                    alarm = {"alarm_type": "smoke", "level": "warning", "confidence": smoke_conf}
                    self.last_alarm_ts = now
        else:
            self.smoke_streak = 0
            if self.status != "normal":
                self.status = "normal"
                self.risk = 0

        return self.status, self.risk, alarm
```

- [ ] **Step 3: 跑测试**

`ai\.venv\Scripts\python -m pytest backend/tests/test_alarm_engine.py -q` 预期 3 passed。

- [ ] **Step 4: 提交**

```bash
git add backend
git commit -m "feat(backend): 告警状态机（连续帧/阈值/冷却）"
```

---

### Task 3: 事件通道与真实模型检测器

**Files:**
- Create: `backend/app/events.py`、`backend/app/detector.py`、`backend/tests/test_detector.py`

**Interfaces:**
- Consumes: Task 1 `config.MODEL_PATH`；ai venv 中 Ultralytics 权重。
- Produces: `WsManager`；`YoloDetector(frame)->list[{type,confidence,bbox}]`。

- [ ] **Step 1: 写入 events.py**

```python
from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import WebSocket


class WsManager:
    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()
        self.loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self.clients.discard(ws)

    async def broadcast(self, payload: dict[str, Any]) -> None:
        text = json.dumps(payload, ensure_ascii=False)
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    def sync_broadcast(self, payload: dict[str, Any]) -> None:
        if self.loop is None:
            return
        asyncio.run_coroutine_threadsafe(self.broadcast(payload), self.loop)
```

- [ ] **Step 2: 写检测器测试（先失败）**

`backend/tests/test_detector.py`：

```python
import cv2

from backend.app.config import ROOT
from backend.app.detector import YoloDetector


def test_detector_on_fire_image() -> None:
    image_dir = ROOT / "datasets" / "fire-smoke-voc" / "VOC2020" / "JPEGImages"
    image = next(iter(image_dir.glob("*.jpg")))
    frame = cv2.imread(str(image))
    det = YoloDetector()
    objects = det.detect(frame)
    assert isinstance(objects, list)
    assert all(o["type"] in {"fire", "smoke"} for o in objects)
```

运行预期 FAIL（detector 不存在）。

- [ ] **Step 3: 实现 YoloDetector**

`backend/app/detector.py`：

```python
from __future__ import annotations

import threading
from typing import Any

import cv2

from .config import MODEL_PATH


class YoloDetector:
    def __init__(self, model_path: str | None = None) -> None:
        from ultralytics import YOLO

        path = str(model_path or MODEL_PATH)
        self.model = YOLO(path)
        self._lock = threading.RLock()
        self.names = {v: str(k).lower() for k, v in self.model.names.items()}

    def detect(self, frame) -> list[dict[str, Any]]:
        import torch

        device = 0 if torch.cuda.is_available() else "cpu"
        with self._lock:
            results = self.model.predict(frame, imgsz=640, conf=0.1, device=device, verbose=False)
        out: list[dict[str, Any]] = []
        for r in results:
            if r.boxes is None:
                continue
            xyxy = r.boxes.xyxy.cpu().numpy()
            confs = r.boxes.conf.cpu().numpy()
            cls = r.boxes.cls.cpu().numpy().astype(int)
            for box, c, ci in zip(xyxy, confs, cls):
                name = self.names.get(int(ci), "unknown")
                if name not in {"fire", "smoke"}:
                    continue
                x1, y1, x2, y2 = map(float, box)
                out.append(
                    {
                        "type": name,
                        "confidence": float(c),
                        "bbox": [round(x1), round(y1), round(x2 - x1), round(y2 - y1)],
                    }
                )
        return out


def draw_detections(frame, detections: list[dict[str, Any]]) -> None:
    for d in detections:
        x, y, w, h = d["bbox"]
        color = (0, 0, 255) if d["type"] == "fire" else (0, 165, 255)
        cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
        label = f"{d['type']} {d['confidence']:.2f}"
        cv2.putText(frame, label, (x, max(0, y - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
```

- [ ] **Step 4: 跑检测器测试**

`ai\.venv\Scripts\python -m pytest backend/tests/test_detector.py -q` 预期 1 passed（首次加载权重较慢）。

- [ ] **Step 5: 提交**

```bash
git add backend
git commit -m "feat(backend): WebSocket 管理器与 YOLO 检测器"
```

---

### Task 4: 检测 worker（读流→推理→告警→画框→缓存帧）

**Files:**
- Create: `backend/app/worker.py`

**Interfaces:**
- Consumes: `db`、`AlarmEngine`、`YoloDetector`、`WsManager`、`draw_detections`、`config`。
- Produces: `DetectionWorker`：属性 `latest_jpeg: bytes|None`、`stop()`；启动后持续广播 detection/alarm/camera_online/camera_offline。

- [ ] **Step 1: 实现 worker**

`backend/app/worker.py`：

```python
from __future__ import annotations

import threading
import time
from typing import Any, Callable

import cv2

from . import db
from .alarm_engine import AlarmEngine
from .config import DEFAULT_FPS, FRAME_QUALITY
from .detector import draw_detections
from .events import WsManager


class DetectionWorker(threading.Thread):
    def __init__(
        self,
        camera: dict[str, Any],
        detector,
        ws: WsManager,
        settings_provider: Callable[[], dict[str, Any]],
    ) -> None:
        super().__init__(daemon=True)
        self.camera = camera
        self.camera_id = int(camera["id"])
        self.detector = detector
        self.ws = ws
        self.settings_provider = settings_provider
        self._stop = threading.Event()
        self.latest_jpeg: bytes | None = None
        self.engine = AlarmEngine()

    def stop(self) -> None:
        self._stop.set()

    def _send(self, payload: dict[str, Any]) -> None:
        self.ws.sync_broadcast(payload)

    def run(self) -> None:
        retries = 0
        while not self._stop.is_set():
            cap = cv2.VideoCapture(self.camera["source"])
            if not cap.isOpened():
                retries += 1
                if self.camera["online"]:
                    db.set_camera_online(self.camera_id, False)
                    self.camera["online"] = 0
                    self._send({"event": "camera_offline", "camera_id": self.camera_id})
                time.sleep(min(60, 1 << min(retries, 6)))
                continue
            retries = 0
            if not self.camera["online"]:
                db.set_camera_online(self.camera_id, True)
                self.camera["online"] = 1
                self._send({"event": "camera_online", "camera_id": self.camera_id})
            self.engine.reset()
            loop_enabled = bool(self.camera.get("loop", 1))
            interval = 1.0 / DEFAULT_FPS
            last_detection_ts = 0.0
            while not self._stop.is_set():
                ok, frame = cap.read()
                if not ok:
                    if loop_enabled:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        continue
                    break
                now = time.time()
                objects = self.detector.detect(frame)
                s = self.settings_provider()
                status, risk, alarm = self.engine.update(
                    now,
                    objects,
                    float(s["fire_threshold"]),
                    float(s["smoke_threshold"]),
                    int(s["continuous_frames"]),
                    float(s["alarm_cooldown"]),
                )
                draw_detections(frame, objects)
                ok_jpeg, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), FRAME_QUALITY])
                if ok_jpeg:
                    self.latest_jpeg = buf.tobytes()
                fps = 1.0 / max(0.001, now - last_detection_ts) if last_detection_ts else DEFAULT_FPS
                last_detection_ts = now
                payload = {
                    "event": "detection",
                    "camera_id": self.camera_id,
                    "timestamp": db.now_text(),
                    "fps": round(fps, 1),
                    "objects": objects,
                    "risk_score": risk,
                    "status": status,
                }
                self._send(payload)
                if alarm is not None:
                    record = db.create_alarm(
                        self.camera_id,
                        self.camera["name"],
                        alarm["alarm_type"],
                        alarm["level"],
                        alarm["confidence"],
                    )
                    self._send({"event": "alarm", "alarm": record})
                time.sleep(max(0.0, interval - (time.time() - now)))
            cap.release()
            db.set_camera_online(self.camera_id, False)
            self.camera["online"] = 0
            self._send({"event": "camera_offline", "camera_id": self.camera_id})
            if loop_enabled:
                time.sleep(0.5)
```

- [ ] **Step 2: 提交**

```bash
git add backend/app/worker.py
git commit -m "feat(backend): 每路视频源的检测 worker"
```

---

### Task 5: FastAPI 应用与路由（含 MJPEG 与 WS）

**Files:**
- Create: `backend/app/main.py`、`backend/app/static.py`、`backend/tests/test_api.py`

**Interfaces:**
- Consumes: Task 1~4 全部模块。
- Produces: `app = FastAPI(...)`；workers 注册表 `app.state.workers: dict[int, DetectionWorker]`；`start_camera_worker(camera)`/`stop_camera_worker(camera_id)`。

- [ ] **Step 1: 写 API 测试（先失败）**

`backend/tests/test_api.py`：

```python
from fastapi.testclient import TestClient  # noqa: E402

from backend.app.main import app  # noqa: E402

client = TestClient(app)


def test_health_settings_and_cameras() -> None:
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/settings").json()["fire_threshold"] == 0.5
    assert client.get("/api/cameras").json() == []


def test_camera_crud_and_toggle() -> None:
    cid = client.post("/api/cameras", json={"name": "演示源", "source_type": "file", "source": "C:/tmp/a.mp4"}).json()["id"]
    cameras = client.get("/api/cameras").json()
    assert any(c["id"] == cid for c in cameras)
    assert client.post(f"/api/cameras/{cid}/toggle").json() == {"id": cid, "enabled": 0}
    client.delete(f"/api/cameras/{cid}")
```

注意：TestClient 生命周期会启动真实模型与 worker，测试只需通过即可；文件源不存在时 worker 会自动重连并标离线，不阻塞测试。

- [ ] **Step 2: 实现 main.py**

```python
from __future__ import annotations

import asyncio
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import db
from .config import FRONTEND_DIST, MODEL_PATH, UPLOADS
from .detector import YoloDetector
from .events import WsManager
from .worker import DetectionWorker


class CameraCreate(BaseModel):
    name: str = Field(min_length=1)
    location: str = ""
    source_type: str = Field(pattern="^(file|rtsp|http)$")
    source: str
    loop: bool = True


class SettingsPayload(BaseModel):
    fire_threshold: float = Field(ge=0.1, le=0.99)
    smoke_threshold: float = Field(ge=0.1, le=0.99)
    continuous_frames: int = Field(ge=1, le=30)
    alarm_cooldown: int = Field(ge=1, le=120)


class CameraRegistry:
    def __init__(self) -> None:
        self.workers: dict[int, DetectionWorker] = {}
        self.detector: YoloDetector | None = None
        self.ws = WsManager()

    def start_camera(self, camera: dict[str, Any]) -> None:
        if not camera["enabled"] or camera["id"] in self.workers:
            return
        w = DetectionWorker(camera, self.detector, self.ws, db.get_settings)
        self.workers[camera["id"]] = w
        w.start()

    def stop_camera(self, camera_id: int) -> None:
        w = self.workers.pop(camera_id, None)
        if w:
            w.stop()


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db.init_db()
        if not MODEL_PATH.is_file():
            raise RuntimeError(f"模型不存在: {MODEL_PATH}，请先完成 AI 训练")
        registry = CameraRegistry()
        registry.detector = YoloDetector(str(MODEL_PATH))
        registry.ws.set_loop(asyncio.get_running_loop())
        app.state.registry = registry
        for camera in db.list_cameras():
            registry.start_camera(camera)
        yield
        for w in list(registry.workers.values()):
            w.stop()

    app = FastAPI(title="FireGuard AI Backend", version="0.2.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def registry() -> CameraRegistry:
        return app.state.registry

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "service": "FireGuard AI", "time": db.now_text()}

    @app.get("/api/cameras")
    def cameras() -> list[dict[str, Any]]:
        return db.list_cameras()

    @app.post("/api/cameras")
    def add_camera(payload: CameraCreate, reg: CameraRegistry = Depends(registry)) -> dict[str, Any]:
        cid = db.insert_camera(payload.name, payload.source_type, payload.source, payload.location, 1 if payload.loop else 0)
        camera = db.get_camera(cid)
        reg.start_camera(camera)
        return camera

    @app.post("/api/uploads")
    async def upload(file: UploadFile = File(...), reg: CameraRegistry = Depends(registry)) -> dict[str, Any]:
        name = file.filename or "upload.mp4"
        if Path(name).suffix.lower() not in {".mp4", ".mov"}:
            raise HTTPException(400, "仅支持 MP4/MOV")
        UPLOADS.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^\w.-]", "_", name)
        target = UPLOADS / f"{int(time.time())}_{safe}"
        target.write_bytes(await file.read())
        cid = db.insert_camera(Path(name).stem, "file", str(target.as_posix()))
        camera = db.get_camera(cid)
        reg.start_camera(camera)
        return camera

    @app.post("/api/cameras/{camera_id}/toggle")
    def toggle(camera_id: int, reg: CameraRegistry = Depends(registry)) -> dict[str, Any]:
        camera = db.get_camera(camera_id)
        if not camera:
            raise HTTPException(404, "camera not found")
        enabled = not bool(camera["enabled"])
        db.set_camera_enabled(camera_id, enabled)
        if enabled:
            camera["enabled"] = 1
            reg.start_camera(camera)
        else:
            reg.stop_camera(camera_id)
        return {"id": camera_id, "enabled": 1 if enabled else 0}

    @app.delete("/api/cameras/{camera_id}")
    def delete(camera_id: int, reg: CameraRegistry = Depends(registry)) -> dict[str, Any]:
        reg.stop_camera(camera_id)
        db.delete_camera(camera_id)
        return {"ok": True, "id": camera_id}

    @app.get("/api/alarms")
    def alarms(limit: int = 100) -> list[dict[str, Any]]:
        return db.list_alarms(min(limit, 500))

    @app.post("/api/alarms/{alarm_id}/ack")
    def ack(alarm_id: int) -> dict[str, Any]:
        if not db.ack_alarm(alarm_id):
            raise HTTPException(404, "alarm not found or already handled")
        return {"ok": True, "id": alarm_id}

    @app.get("/api/settings")
    def settings() -> dict[str, Any]:
        return db.get_settings()

    @app.put("/api/settings")
    def put_settings(payload: SettingsPayload) -> dict[str, Any]:
        return db.put_settings(payload.model_dump())

    @app.get("/api/dashboard")
    def dashboard() -> dict[str, Any]:
        return db.dashboard_stats()

    @app.get("/stream/{camera_id}")
    async def stream(camera_id: int, reg: CameraRegistry = Depends(registry)):
        w = reg.workers.get(camera_id)
        if not w:
            raise HTTPException(404, "worker not running")

        async def gen():
            deadline = time.time() + 30
            while True:
                frame = w.latest_jpeg
                if frame:
                    yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
                    deadline = time.time() + 30
                elif time.time() > deadline:
                    break
                await asyncio.sleep(0.1)

        return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame")

    @app.websocket("/ws/events")
    async def ws_events(ws: WebSocket, reg: CameraRegistry = Depends(registry)):
        await reg.ws.connect(ws)
        await ws.send_json({"event": "connected", "message": "实时检测通道已连接"})
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            reg.ws.disconnect(ws)

    return app


app = create_app()
```

- [ ] **Step 3: 静态托管（可选文件）**

`backend/app/static.py`：

```python
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import FRONTEND_DIST


def mount_frontend(app: FastAPI) -> None:
    if not (FRONTEND_DIST / "index.html").is_file():
        return
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(FRONTEND_DIST / "index.html")
```

并在 main.py 末尾调用 `mount_frontend(app)`（需在 `app = create_app()` 后导入调用；静态托管不参与本计划测试）。

- [ ] **Step 4: 运行 API 测试**

```powershell
ai\.venv\Scripts\python -m pytest backend/tests -q
```

预期：全部通过（db/engine/detector/api）。若 ultralytics 首次加载慢，设置 `PYTHONWARNINGS=ignore` 不必须。

- [ ] **Step 5: 提交**

```bash
git add backend
git commit -m "feat(backend): FastAPI 应用（cameras/uploads/alarms/settings/stream/WS）"
```

---

### Task 6: 端到端冒烟（真实模型 + 生成演示视频）

**Files:**
- Create: `scripts/make_demo_video.py`
- Test: 手工运行验证

**Interfaces:**
- Consumes: 训练好的 `best.pt` 与数据集图片。
- Produces: `storage/uploads/demo_fire.mp4`（循环测试视频）。

- [ ] **Step 1: 生成演示视频**

`scripts/make_demo_video.py`：

```python
from pathlib import Path

import cv2

root = Path(__file__).resolve().parents[1]
img_dir = root / "datasets" / "fire-smoke-voc" / "VOC2020" / "JPEGImages"
images = sorted(img_dir.glob("*.jpg"))[:24]
out = root / "storage" / "uploads"
out.mkdir(parents=True, exist_ok=True)
target = out / "demo_fire.mp4"
writer = None
for p in images:
    img = cv2.imread(str(p))
    if img is None:
        continue
    if writer is None:
        h, w = img.shape[:2]
        writer = cv2.VideoWriter(str(target), cv2.VideoWriter_fourcc(*"mp4v"), 6, (w, h))
    for _ in range(3):
        writer.write(img)
writer.release()
print(target)
```

运行：`ai\.venv\Scripts\python scripts\make_demo_video.py`，预期打印 `...demo_fire.mp4`。

- [ ] **Step 2: 启动后端并验证**

```powershell
ai\.venv\Scripts\python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

另一终端验证：

```powershell
curl http://127.0.0.1:8000/api/health
curl -F "file=@storage/uploads/demo_fire.mp4" http://127.0.0.1:8000/api/uploads
curl http://127.0.0.1:8000/api/cameras
curl http://127.0.0.1:8000/api/dashboard
```

预期：upload 返回 file 型摄像头且 enabled=1；dashboard 返回 online 摄像头数；日志出现 detection 推送。

- [ ] **Step 3: 验证 MJPEG 首帧**

`curl -N --max-time 5 http://127.0.0.1:8000/stream/1 -o stream.out`，预期文件以 JPEG 二进制（`FF D8`）开头。

- [ ] **Step 4: 停服务并提交脚本**

```powershell
git add scripts/make_demo_video.py
git commit -m "feat(scripts): 生成演示 MP4 用于端到端冒烟"
```
