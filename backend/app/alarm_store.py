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
    """告警落库 + 画面留存 + 推送入队；画面落盘失败绝不能连累已入库的告警。"""
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
    # 先把推送排进队列，再去碰文件系统：磁盘写失败时推送也已经出去了
    record["pushed"] = False
    if is_new and notifier is not None:
        notifier.enqueue_alarm(record)
        record["pushed"] = True
    if frame_jpeg:
        try:
            first_path = snapshots.store_frame(camera_id, alarm_id, "first", frame_jpeg) if is_new else None
            latest_path = snapshots.store_frame(camera_id, alarm_id, "latest", frame_jpeg)
            boxes = json.dumps(visible, ensure_ascii=False)
            width, height = frame_size
            size_text = f"{int(width)}x{int(height)}"
            db.update_alarm_snapshot(
                alarm_id,
                first=first_path,
                latest=latest_path,
                boxes=boxes,
                frame_size=size_text,
            )
        except Exception:  # noqa: BLE001
            pass  # 画面留存失败可接受（库里有记录、推送已发出），不能向上抛
        else:
            if first_path:
                record["snapshot_first"] = first_path
            record["snapshot_latest"] = latest_path
            record["boxes"] = boxes
            record["frame_size"] = size_text
    return record
