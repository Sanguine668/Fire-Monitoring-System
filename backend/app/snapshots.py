"""告警画面帧的文件操作：只负责落盘、解析与清理，不碰数据库。"""

from __future__ import annotations

import time
from pathlib import Path

from .config import SNAPSHOTS

VARIANTS = ("first", "latest")


def alarm_frame_path(camera_id: int, alarm_id: int, variant: str) -> Path:
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant: {variant}")
    return SNAPSHOTS / str(int(camera_id)) / f"alarm_{int(alarm_id)}_{variant}.jpg"


def store_frame(camera_id: int, alarm_id: int, variant: str, jpeg: bytes) -> str:
    """写入画面帧，返回相对 SNAPSHOTS 的路径，用于存库。"""
    path = alarm_frame_path(camera_id, alarm_id, variant)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(jpeg)
    return path.relative_to(SNAPSHOTS).as_posix()


def resolve_frame(rel_path: str) -> Path | None:
    """把库里存的相对路径还原成磁盘路径；越界或不存在都返回 None。"""
    if not rel_path:
        return None
    root = SNAPSHOTS.resolve()
    candidate = (root / rel_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def delete_alarm_frames(camera_id: int, alarm_id: int) -> int:
    removed = 0
    for variant in VARIANTS:
        path = alarm_frame_path(camera_id, alarm_id, variant)
        if path.is_file():
            try:
                path.unlink()
                removed += 1
            except OSError:
                continue
    return removed


def cleanup_old_frames(days: int = 7, now: float | None = None) -> int:
    """删除超过保留期的画面帧，并顺手清掉空目录。"""
    if not SNAPSHOTS.is_dir():
        return 0
    cutoff = (now if now is not None else time.time()) - days * 86400
    removed = 0
    for path in SNAPSHOTS.glob("*/*.jpg"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            continue
    for folder in SNAPSHOTS.iterdir():
        if folder.is_dir() and not any(folder.iterdir()):
            try:
                folder.rmdir()
            except OSError:
                continue
    return removed
