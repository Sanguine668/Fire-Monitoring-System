"""一次告警的完整留存：写库、存两张画面帧、交给推送线程。"""

from __future__ import annotations

import json
from typing import Any

from . import db, snapshots


def persist_alarm(
    camera_id: int,
    camera_name: str,
    alarm: dict[str, Any],
    visible: list[dict[str, Any]],
    frame_jpeg: bytes,
    frame_size: tuple[int, int],
    notifier: Any | None = None,
) -> dict[str, Any]:
    record = db.create_alarm(
        camera_id,
        camera_name,
        alarm["alarm_type"],
        alarm["level"],
        alarm["confidence"],
        1 if alarm.get("verified") else 0,
    )
    is_new = bool(record.get("is_new"))
    alarm_id = int(record["id"])
    if frame_jpeg:
        if is_new:
            record["snapshot_first"] = snapshots.store_frame(camera_id, alarm_id, "first", frame_jpeg)
        record["snapshot_latest"] = snapshots.store_frame(camera_id, alarm_id, "latest", frame_jpeg)
        record["boxes"] = json.dumps(visible, ensure_ascii=False)
        width, height = frame_size
        db.update_alarm_snapshot(
            alarm_id,
            first=record.get("snapshot_first") if is_new else None,
            latest=record["snapshot_latest"],
            boxes=record["boxes"],
            frame_size=f"{int(width)}x{int(height)}",
        )
        record["frame_size"] = f"{int(width)}x{int(height)}"
    record["pushed"] = False
    if is_new and notifier is not None:
        notifier.enqueue_alarm(record)
        record["pushed"] = True
    return record
