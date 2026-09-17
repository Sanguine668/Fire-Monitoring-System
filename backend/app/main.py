from __future__ import annotations

import asyncio
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import db
from .config import MODEL_PATH, UPLOADS
from .detector import YoloDetector
from .events import WsManager
from .static import mount_frontend
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


class AckGroupPayload(BaseModel):
    camera_id: int
    alarm_type: str = Field(pattern="^(fire|smoke)$")


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

    @app.post("/api/alarms/ack_group")
    def ack_group(payload: AckGroupPayload) -> dict[str, Any]:
        count = db.ack_alarm_group(payload.camera_id, payload.alarm_type)
        if count == 0:
            raise HTTPException(404, "no unhandled alarm found for this camera and type")
        return {"ok": True, "handled": count}

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
    async def stream(camera_id: int, annotated: bool = True, reg: CameraRegistry = Depends(registry)):
        w = reg.workers.get(camera_id)
        if not w:
            raise HTTPException(404, "worker not running")

        async def gen():
            deadline = time.time() + 30
            while True:
                frame = w.latest_jpeg if annotated else w.latest_raw_jpeg
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
mount_frontend(app)
