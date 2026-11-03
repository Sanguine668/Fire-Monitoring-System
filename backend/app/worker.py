from __future__ import annotations

import collections
import threading
import time
from typing import Any, Callable

import cv2

from . import alarm_store, db
from .alarm_engine import AlarmEngine
from .config import DEFAULT_FPS, FRAME_QUALITY
from .detector import draw_detections
from .distance import estimate_distance
from .events import WsManager
from .sources import is_network_source, open_capture
from .tiling import merge_detections
from .verifier import prepare_crop

NETWORK_RETRY_CAP = 10.0
FILE_RETRY_CAP = 60.0


class DetectionWorker(threading.Thread):
    def __init__(
        self,
        camera: dict[str, Any],
        detector,
        ws: WsManager,
        settings_provider: Callable[[], dict[str, Any]],
        notifier: Any | None = None,
    ) -> None:
        super().__init__(daemon=True)
        self.camera = camera
        self.camera_id = int(camera["id"])
        self.detector = detector
        self.ws = ws
        self.settings_provider = settings_provider
        self.notifier = notifier
        self._stop = threading.Event()
        self.latest_jpeg: bytes | None = None
        self.latest_raw_jpeg: bytes | None = None
        self.engine = AlarmEngine()
        self._last_tile_ts = 0.0
        self._tile_objects: list[dict[str, Any]] = []
        self._tile_expire = 0.0
        self._last_event_ts = 0.0
        # 证据抽屉：留最近几帧原始缩略图、最近一次候选框与复核裁剪，
        # 供 /api/agents/evidence 现场出图（全部来自真实采集帧）。
        self._evidence_frames: collections.deque = collections.deque(maxlen=5)
        self._last_objects: list[dict[str, Any]] = []
        self._last_verify: dict[str, Any] | None = None
        self._last_trace: dict[str, Any] | None = None
        # 复核只在"即将产生告警"的那一帧执行（约 0.25 秒），前端 3 秒采样几乎抓不到；
        # 因此累计统计并通过 trace 下发，让智能体页能看见它确实一直在工作。
        self._verify_stats: dict[str, Any] = {
            "total": 0,
            "passed": 0,
            "blocked": 0,
            "last_ts": "",
            "last_passed": None,
            "last_confidence": None,
        }

    def _record_verify(self, passed: bool, confidence: float) -> None:
        self._verify_stats["total"] += 1
        if passed:
            self._verify_stats["passed"] += 1
        else:
            self._verify_stats["blocked"] += 1
        self._verify_stats["last_ts"] = db.now_text()
        self._verify_stats["last_passed"] = bool(passed)
        self._verify_stats["last_confidence"] = round(float(confidence), 3)

    def _remember_evidence_frame(self, frame, objects: list[dict[str, Any]]) -> None:
        """把当前原始帧压成 320px 缩略图留档，供证据抽屉拼「最近 5 帧」。"""
        h, w = frame.shape[:2]
        if w <= 0 or h <= 0:
            return
        thumb = cv2.resize(frame, (320, max(1, round(h * 320 / w))), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", thumb, [int(cv2.IMWRITE_JPEG_QUALITY), 60])
        if not ok:
            return
        smoke = max((d["confidence"] for d in objects if d["type"] == "smoke"), default=0.0)
        self._evidence_frames.append({
            "ts": db.now_text()[11:],
            "objects": len(objects),
            "smoke": round(float(smoke), 3),
            "jpeg": buf.tobytes(),
        })

    def _remember_verify(
        self,
        frame: Any | None,
        bbox: list[int] | None,
        alarm_type: str,
        confidence: float,
        passed: bool,
        threshold: float,
    ) -> None:
        """留档复核裁出的真实局部图；找不到触发目标时 crop 为空。"""
        crop_bytes = None
        if frame is not None and bbox:
            crop = prepare_crop(frame, list(bbox), 0.25)
            if crop.size:
                h, w = crop.shape[:2]
                if min(h, w) < 200:
                    crop = cv2.resize(crop, (w * 2, h * 2), interpolation=cv2.INTER_NEAREST)
                ok, buf = cv2.imencode(".jpg", crop, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
                if ok:
                    crop_bytes = buf.tobytes()
        self._last_verify = {
            "ts": db.now_text()[11:],
            "crop": crop_bytes,
            "bbox": list(bbox) if bbox else None,
            "type": alarm_type,
            "confidence": round(float(confidence), 3),
            "passed": bool(passed),
            "threshold": float(threshold),
        }

    def stop(self) -> None:
        self._stop.set()

    def _send(self, payload: dict[str, Any]) -> None:
        self.ws.sync_broadcast(payload)

    def run(self) -> None:
        retries = 0
        retry_cap = NETWORK_RETRY_CAP if is_network_source(self.camera["source"]) else FILE_RETRY_CAP
        while not self._stop.is_set():
            cap = open_capture(self.camera["source"])
            if not cap.isOpened():
                retries += 1
                if self.camera["online"]:
                    db.set_camera_online(self.camera_id, False)
                    self.camera["online"] = 0
                    self._send({"event": "camera_offline", "camera_id": self.camera_id})
                time.sleep(min(retry_cap, float(1 << min(retries, 6))))
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
                s = self.settings_provider()
                tiling_on = bool(int(s.get("tiling_enabled", 0)))
                use_tiling = tiling_on and (
                    now - self._last_tile_ts >= float(s.get("tile_interval", 2))
                )
                if use_tiling:
                    objects = self.detector.detect_tiled(
                        frame,
                        tile_size=int(s.get("tile_size", 640)),
                        overlap=float(s.get("tile_overlap", 0.2)),
                    )
                    self._last_tile_ts = now
                    self._tile_objects = objects
                    self._tile_expire = now + float(s.get("tile_interval", 2))
                else:
                    objects = self.detector.detect(frame)
                    # 切片间隔内保持远景结果，避免烟雾告警因普通帧漏检而断档
                    if self._tile_objects and now < self._tile_expire:
                        objects = merge_detections(objects + self._tile_objects, 0.5)
                # 证据抽屉用的现场快照必须在画框之前采集，保证是未经标注的原始帧
                self._last_objects = list(objects)
                self._remember_evidence_frame(frame, objects)
                status, risk, alarm = self.engine.update(
                    now,
                    objects,
                    float(s["fire_threshold"]),
                    float(s["smoke_threshold"]),
                    int(s["continuous_frames"]),
                    float(s["alarm_cooldown"]),
                )
                verify_enabled = bool(int(s.get("verify_enabled", 1)))
                verification_state = {
                    "active": verify_enabled,
                    "triggered": False,
                    "passed": None,
                    "confidence": None,
                    "history": dict(self._verify_stats),
                }
                if alarm is not None and verify_enabled:
                    verification_state["triggered"] = True
                    trigger = max(
                        (d for d in objects if d["type"] == alarm["alarm_type"]),
                        key=lambda d: d["confidence"],
                        default=None,
                    )
                    if trigger is None:
                        verification_state["passed"] = False
                        self._record_verify(False, 0.0)
                        self._remember_verify(
                            None,
                            None,
                            alarm["alarm_type"],
                            0.0,
                            False,
                            float(s.get("verify_threshold", 0.2)),
                        )
                        alarm = None
                    else:
                        verified, verify_conf = self.detector.verify_region(
                            frame,
                            trigger["bbox"],
                            alarm["alarm_type"],
                            float(s.get("verify_threshold", 0.2)),
                        )
                        verification_state["confidence"] = round(verify_conf, 3)
                        verification_state["passed"] = verified
                        self._record_verify(verified, verify_conf)
                        self._remember_verify(
                            frame,
                            trigger["bbox"],
                            alarm["alarm_type"],
                            verify_conf,
                            verified,
                            float(s.get("verify_threshold", 0.2)),
                        )
                        if not verified:
                            self.engine.last_alarm_ts = -1e9
                            alarm = None
                        else:
                            alarm["verified"] = True
                            alarm["verify_confidence"] = round(verify_conf, 3)
                    verification_state["history"] = dict(self._verify_stats)
                visible = [
                    d
                    for d in objects
                    if (d["type"] == "fire" and d["confidence"] >= float(s["fire_threshold"]))
                    or (d["type"] == "smoke" and d["confidence"] >= float(s["smoke_threshold"]))
                ]
                # 安装参数与预设每次从 DB 行读取；API 改完后 Worker 无需重启即可生效。
                geometry = {
                    "preset": self.camera.get("geometry_preset"),
                    "install_height_m": self.camera.get("install_height_m"),
                    "pitch_deg": self.camera.get("pitch_deg"),
                    "hfov_deg": self.camera.get("hfov_deg"),
                }
                for d in visible:
                    d["distance"] = estimate_distance(
                        d["bbox"],
                        frame.shape[1],
                        frame.shape[0],
                        geometry,
                        alarm_type=d["type"],
                    )
                nearest = min(
                    visible,
                    key=lambda d: d["distance"]["meters"],
                    default=None,
                )
                trace = {
                    "perception": {
                        "active": True,
                        "objects": len(objects),
                        "top_confidence": round(max((d["confidence"] for d in objects), default=0.0), 3),
                        "nearest_m": nearest["distance"]["meters"] if nearest else None,
                        "nearest_band": nearest["distance"]["band"] if nearest else None,
                    },
                    "farfield": {
                        "active": use_tiling,
                        "enabled": tiling_on,
                        "tile_size": int(s.get("tile_size", 640)),
                        "interval": int(s.get("tile_interval", 2)),
                        "held": len(self._tile_objects),
                    },
                    "temporal": {
                        "smoke_streak": self.engine.smoke_streak,
                        "required": int(s["continuous_frames"]),
                        "cooldown": int(s["alarm_cooldown"]),
                    },
                    "verification": verification_state,
                    "decision": {
                        "status": status,
                        "risk": risk,
                        "alarm": alarm is not None,
                    },
                }
                self._last_trace = trace
                ok_raw, raw_buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), FRAME_QUALITY])
                if ok_raw:
                    self.latest_raw_jpeg = raw_buf.tobytes()
                draw_detections(frame, visible)
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
                    "tiled": use_tiling,
                    "agents": trace,
                }
                # 视频保持 4 FPS，但 WebSocket 状态 2 秒一次即可，减少前端重渲染
                if now - self._last_event_ts >= 0.5:
                    self._send(payload)
                    self._last_event_ts = now
                if alarm is not None:
                    try:
                        record = alarm_store.persist_alarm(
                            camera_id=self.camera_id,
                            camera_name=self.camera["name"],
                            alarm=alarm,
                            visible=visible,
                            frame_jpeg=self.latest_jpeg or b"",
                            frame_size=(frame.shape[1], frame.shape[0]),
                            notifier=self.notifier,
                        )
                    except Exception as exc:  # noqa: BLE001
                        record = None
                        self._send({"event": "alarm_error", "camera_id": self.camera_id, "message": str(exc)[:200]})
                    if record is not None:
                        record["agents"] = trace
                        self._send({"event": "alarm", "alarm": record})
                time.sleep(max(0.0, interval - (time.time() - now)))
            cap.release()
            db.set_camera_online(self.camera_id, False)
            self.camera["online"] = 0
            self._send({"event": "camera_offline", "camera_id": self.camera_id})
            if loop_enabled:
                time.sleep(0.5)
