from __future__ import annotations

import asyncio
import json
import random
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "storage" / "fire_alert.db"
FRONTEND = ROOT / "frontend"


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS cameras (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                location TEXT NOT NULL,
                source TEXT NOT NULL,
                online INTEGER NOT NULL DEFAULT 1,
                enabled INTEGER NOT NULL DEFAULT 1
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
        if conn.execute("SELECT COUNT(*) c FROM cameras").fetchone()["c"] == 0:
            conn.executemany(
                "INSERT INTO cameras(id,name,location,source,online,enabled) VALUES(?,?,?,?,?,?)",
                [
                    (1, "仓库东区-01", "原料仓库东侧", "rtsp://demo/camera01", 1, 1),
                    (2, "生产线-02", "二号生产线", "rtsp://demo/camera02", 1, 1),
                    (3, "配电室-03", "一层配电室", "rtsp://demo/camera03", 1, 1),
                    (4, "停车区-04", "厂区停车区", "rtsp://demo/camera04", 1, 1),
                ],
            )
        defaults = {
            "fire_threshold": "0.62",
            "smoke_threshold": "0.55",
            "continuous_frames": "4",
            "alarm_cooldown": "8",
        }
        for k, v in defaults.items():
            conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
        conn.commit()


class DemoState:
    mode: Literal["normal", "smoke", "fire"] = "normal"
    mode_until: float = 0.0
    seq: int = 0
    last_alarm_ts: float = 0.0


state = DemoState()
clients: set[WebSocket] = set()


async def broadcast(payload: dict) -> None:
    dead = []
    for ws in clients:
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        clients.discard(ws)


def create_alarm(alarm_type: str, confidence: float, level: str, camera_id: int = 1) -> dict:
    with db() as conn:
        camera = conn.execute("SELECT * FROM cameras WHERE id=?", (camera_id,)).fetchone()
        if not camera:
            raise ValueError("camera not found")
        created_at = now_text()
        cur = conn.execute(
            "INSERT INTO alarms(camera_id,camera_name,alarm_type,level,confidence,created_at,status) VALUES(?,?,?,?,?,?,?)",
            (camera_id, camera["name"], alarm_type, level, confidence, created_at, "unhandled"),
        )
        conn.commit()
        return {
            "id": cur.lastrowid,
            "camera_id": camera_id,
            "camera_name": camera["name"],
            "alarm_type": alarm_type,
            "level": level,
            "confidence": round(confidence, 3),
            "created_at": created_at,
            "status": "unhandled",
        }


def current_detection() -> dict:
    import time

    state.seq += 1
    if time.time() > state.mode_until:
        state.mode = "normal"

    base = {
        "event": "detection",
        "seq": state.seq,
        "camera_id": 1,
        "timestamp": now_text(),
        "fps": round(random.uniform(7.4, 9.8), 1),
        "latency_ms": random.randint(28, 54),
        "objects": [],
        "risk_score": random.randint(2, 12),
        "status": "normal",
    }

    if state.mode == "smoke":
        conf = random.uniform(0.68, 0.91)
        base.update(
            status="warning",
            risk_score=random.randint(48, 67),
            objects=[{"type": "smoke", "confidence": round(conf, 3), "bbox": [42, 19, 35, 47]}],
        )
    elif state.mode == "fire":
        conf = random.uniform(0.82, 0.97)
        base.update(
            status="critical",
            risk_score=random.randint(82, 98),
            objects=[
                {"type": "fire", "confidence": round(conf, 3), "bbox": [47, 48, 22, 31]},
                {"type": "smoke", "confidence": round(random.uniform(0.61, 0.88), 3), "bbox": [40, 17, 37, 36]},
            ],
        )
    return base


async def detection_loop() -> None:
    import time

    while True:
        payload = current_detection()
        await broadcast(payload)
        if state.mode in {"smoke", "fire"}:
            with db() as conn:
                row = conn.execute("SELECT value FROM settings WHERE key='alarm_cooldown'").fetchone()
                cooldown = int(float(row["value"])) if row else 8
            if time.time() - state.last_alarm_ts <= cooldown:
                await asyncio.sleep(1)
                continue
            if state.mode == "fire":
                alarm = create_alarm("fire", payload["objects"][0]["confidence"], "critical")
            else:
                alarm = create_alarm("smoke", payload["objects"][0]["confidence"], "warning")
            state.last_alarm_ts = time.time()
            await broadcast({"event": "alarm", "alarm": alarm})
        await asyncio.sleep(1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    task = asyncio.create_task(detection_loop())
    yield
    task.cancel()


app = FastAPI(title="FireGuard AI", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SettingsPayload(BaseModel):
    fire_threshold: float = Field(ge=0.1, le=0.99)
    smoke_threshold: float = Field(ge=0.1, le=0.99)
    continuous_frames: int = Field(ge=1, le=30)
    alarm_cooldown: int = Field(ge=1, le=120)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "FireGuard AI", "time": now_text()}


@app.get("/api/cameras")
def cameras():
    with db() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM cameras ORDER BY id").fetchall()]


@app.post("/api/cameras/{camera_id}/toggle")
def toggle_camera(camera_id: int):
    with db() as conn:
        row = conn.execute("SELECT * FROM cameras WHERE id=?", (camera_id,)).fetchone()
        if not row:
            raise HTTPException(404, "camera not found")
        new_value = 0 if row["enabled"] else 1
        conn.execute("UPDATE cameras SET enabled=? WHERE id=?", (new_value, camera_id))
        conn.commit()
        return {"id": camera_id, "enabled": new_value}


@app.get("/api/alarms")
def alarms(limit: int = 50):
    with db() as conn:
        rows = conn.execute("SELECT * FROM alarms ORDER BY id DESC LIMIT ?", (min(limit, 200),)).fetchall()
        return [dict(r) for r in rows]


@app.post("/api/alarms/{alarm_id}/ack")
def ack_alarm(alarm_id: int):
    with db() as conn:
        cur = conn.execute("UPDATE alarms SET status='handled' WHERE id=?", (alarm_id,))
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(404, "alarm not found")
        return {"ok": True, "id": alarm_id}


@app.get("/api/dashboard")
def dashboard():
    with db() as conn:
        camera_count = conn.execute("SELECT COUNT(*) c FROM cameras").fetchone()["c"]
        online_count = conn.execute("SELECT COUNT(*) c FROM cameras WHERE online=1").fetchone()["c"]
        today = datetime.now().strftime("%Y-%m-%d") + "%"
        alarm_count = conn.execute("SELECT COUNT(*) c FROM alarms WHERE created_at LIKE ?", (today,)).fetchone()["c"]
        critical_count = conn.execute("SELECT COUNT(*) c FROM alarms WHERE created_at LIKE ? AND level='critical'", (today,)).fetchone()["c"]
        unhandled = conn.execute("SELECT COUNT(*) c FROM alarms WHERE status='unhandled'").fetchone()["c"]
        recent = [dict(r) for r in conn.execute("SELECT * FROM alarms ORDER BY id DESC LIMIT 5").fetchall()]
    return {
        "camera_count": camera_count,
        "online_count": online_count,
        "today_alarms": alarm_count,
        "critical_alarms": critical_count,
        "unhandled": unhandled,
        "recent": recent,
        "uptime": "99.8%",
    }


@app.get("/api/settings")
def get_settings():
    with db() as conn:
        values = {r["key"]: r["value"] for r in conn.execute("SELECT * FROM settings").fetchall()}
    return {
        "fire_threshold": float(values["fire_threshold"]),
        "smoke_threshold": float(values["smoke_threshold"]),
        "continuous_frames": int(values["continuous_frames"]),
        "alarm_cooldown": int(values["alarm_cooldown"]),
    }


@app.put("/api/settings")
def put_settings(payload: SettingsPayload):
    values = payload.model_dump()
    with db() as conn:
        for k, v in values.items():
            conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (k, str(v)))
        conn.commit()
    return {"ok": True, **values}


@app.post("/api/demo/trigger/{kind}")
async def demo_trigger(kind: Literal["normal", "smoke", "fire"]):
    import time

    state.mode = kind
    state.mode_until = time.time() + (14 if kind != "normal" else 1)
    state.last_alarm_ts = 0
    await broadcast({"event": "demo_mode", "mode": kind, "timestamp": now_text()})
    return {"ok": True, "mode": kind}


@app.websocket("/ws/events")
async def websocket_events(ws: WebSocket):
    await ws.accept()
    clients.add(ws)
    await ws.send_json({"event": "connected", "message": "实时检测通道已连接", "timestamp": now_text()})
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        clients.discard(ws)
    except Exception:
        clients.discard(ws)


app.mount("/assets", StaticFiles(directory=FRONTEND), name="assets")


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")


@app.get("/{path:path}")
def spa(path: str):
    if path.startswith("api/") or path.startswith("ws/"):
        raise HTTPException(404)
    return FileResponse(FRONTEND / "index.html")
