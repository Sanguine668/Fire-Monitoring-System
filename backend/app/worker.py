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
