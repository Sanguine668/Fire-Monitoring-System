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
