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
    tiling_enabled: int = Field(default=1, ge=0, le=1)
    tile_size: int = Field(default=640, ge=320, le=1280)
    tile_overlap: float = Field(default=0.2, ge=0, le=0.5)
    tile_interval: int = Field(default=2, ge=1, le=10)
    verify_enabled: int = Field(default=1, ge=0, le=1)
    verify_threshold: float = Field(default=0.25, ge=0.05, le=0.9)


class AckGroupPayload(BaseModel):
    camera_id: int
    alarm_type: str = Field(pattern="^(fire|smoke)$")


class ProbePayload(BaseModel):
    source: str = Field(min_length=1)


class PhoneProbePayload(BaseModel):
    host: str = Field(min_length=1)


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

    @app.get("/api/network")
    def network_info() -> dict[str, Any]:
        """返回本机局域网地址，供手机接入向导展示。"""
        import socket

        import psutil

        addresses: list[dict[str, str]] = []
        for name, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family != socket.AF_INET:
                    continue
                ip = addr.address
                # 排除回环与 169.254 自动专用地址（没连上网络时才出现的无效地址）
                if ip.startswith("127.") or ip.startswith("169.254."):
                    continue
                addresses.append({"interface": name, "ip": ip})

        def rank(item: dict[str, str]) -> int:
            prefix = item["ip"].split(".")[0]
            # 手机热点网段通常是 192.168.*，其次是 10.*、172.16-31.*
            return {"192": 0, "10": 1, "172": 2}.get(prefix, 3)

        addresses.sort(key=rank)
        preferred = addresses[0]["ip"] if addresses else ""
        return {
            "addresses": addresses,
            "preferred": preferred,
            "dashboard_url": f"http://{preferred}:8000" if preferred else "",
        }

    @app.post("/api/probe")
    def probe_source(payload: ProbePayload) -> dict[str, Any]:
        """试连视频源（手机推流地址或本地文件），返回是否可用与画面尺寸。"""
        import threading

        from .sources import open_capture

        result: dict[str, Any] = {"ok": False, "message": ""}
        source = payload.source.strip()

        def work() -> None:
            cap = None
            try:
                cap = open_capture(source)
                if not cap.isOpened():
                    result["message"] = "无法打开该地址：不可达或格式不支持（请确认手机与电脑在同一网络）"
                    return
                ok, frame = cap.read()
                if not ok or frame is None:
                    result["message"] = "已连通但读不到画面：请确认 IP Webcam 已点 Start server，且地址以 /video 结尾"
                    return
                height, width = frame.shape[:2]
                result.update(ok=True, width=width, height=height, message=f"连接成功，画面 {width}×{height}")
            except Exception as exc:  # noqa: BLE001
                result["message"] = f"探测异常：{exc}"
            finally:
                if cap is not None:
                    cap.release()

        worker = threading.Thread(target=work, daemon=True)
        worker.start()
        worker.join(8)
        if worker.is_alive():
            result["message"] = "连接超时（8 秒），请检查网络与地址"
        return result

    @app.post("/api/probe_phone")
    def probe_phone(payload: PhoneProbePayload) -> dict[str, Any]:
        """并行尝试 IP Webcam 常见端点，返回可用的地址。"""
        from concurrent.futures import ThreadPoolExecutor
        from urllib.parse import urlparse

        from .sources import open_capture

        raw = payload.host.strip()
        if "://" not in raw:
            raw = f"http://{raw}"
        parsed = urlparse(raw)
        host = parsed.hostname or payload.host.strip()
        port = parsed.port or 8080
        candidates = [
            f"http://{host}:{port}/video",
            f"http://{host}:{port}/videofeed",
            f"http://{host}:{port}/shot.jpg",
            f"rtsp://{host}:{port}/h264_ulaw.sdp",
            f"rtsp://{host}:{port}/h264_pcm.sdp",
        ]

        def try_one(url: str) -> dict[str, Any]:
            cap = None
            try:
                cap = open_capture(url, open_timeout_ms=3500, read_timeout_ms=3500)
                ok, frame = cap.read() if cap.isOpened() else (False, None)
                if ok and frame is not None:
                    h, w = frame.shape[:2]
                    return {"url": url, "ok": True, "width": w, "height": h}
                return {"url": url, "ok": False, "message": "未读到画面"}
            except Exception as exc:  # noqa: BLE001
                return {"url": url, "ok": False, "message": str(exc)[:120]}
            finally:
                if cap is not None:
                    try:
                        cap.release()
                    except Exception:
                        pass

        with ThreadPoolExecutor(max_workers=len(candidates)) as pool:
            results = list(pool.map(try_one, candidates))
        working = [r for r in results if r["ok"]]
        return {"ok": bool(working), "working": working, "tried": results}

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

    @app.delete("/api/alarms")
    def clear_alarms() -> dict[str, Any]:
        return {"ok": True, "deleted": db.clear_alarms()}

    @app.get("/api/model")
    def model_info(reg: CameraRegistry = Depends(registry)) -> dict[str, Any]:
        detector = reg.detector
        return {
            "path": MODEL_PATH.name,
            "classes": detector.id2name if detector else {},
            "task": "detect",
        }

    @app.get("/api/agents")
    def agents_info() -> dict[str, Any]:
        """多智能体协同链路的定义、实时参数与评测指标。"""
        return {
            "pipeline": ["perception", "farfield", "temporal", "verification", "decision"],
            "agents": [
                {"key": "perception", "name": "感知 Agent", "role": "整图烟火检测",
                 "desc": "YOLO26n 双类检测，输出 fire/smoke 与置信度"},
                {"key": "farfield", "name": "远场 Agent", "role": "切片扫描",
                 "desc": "每 2 秒切 640 瓦片、20% 重叠、跨片 NMS 合并"},
                {"key": "temporal", "name": "时序 Agent", "role": "连续帧与短时保持",
                 "desc": "切片结果保持、烟雾连续帧确认、告警冷却"},
                {"key": "verification", "name": "复核 Agent", "role": "局部二次检测",
                 "desc": "告警区域裁剪放大后复检，不通过则抑制"},
                {"key": "decision", "name": "决策 Agent", "role": "风险分级与告警合并",
                 "desc": "按阈值、风险和冷却生成或合并告警"},
            ],
            "metrics": {
                "map50": 0.724,
                "map50_95": 0.400,
                "farfield_recall": 0.812,
                "farfield_old": 0.185,
                "hardneg_fpr": 0.342,
                "hardneg_old": 0.527,
                "tiling_plain": 0.940,
                "tiling_tiled": 0.960,
                "smokefire_smoke": 0.908,
                "smokefire_fire": 0.905,
                "calibrated_fire_fpr": 0.048,
            },
            "settings": db.get_settings(),
        }

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
            last_sent = None
            while True:
                frame = w.latest_jpeg if annotated else w.latest_raw_jpeg
                if frame and frame is not last_sent:
                    yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
                    last_sent = frame
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
