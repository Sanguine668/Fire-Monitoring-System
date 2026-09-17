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
                status TEXT NOT NULL DEFAULT 'unhandled',
                count INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        for k, v in {
            "fire_threshold": "0.1",
            "smoke_threshold": "0.1",
            "continuous_frames": "3",
            "alarm_cooldown": "8",
        }.items():
            c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
        columns = {r["name"] for r in c.execute("PRAGMA table_info(alarms)").fetchall()}
        if "count" not in columns:
            c.execute("ALTER TABLE alarms ADD COLUMN count INTEGER NOT NULL DEFAULT 1")
        if "updated_at" not in columns:
            c.execute("ALTER TABLE alarms ADD COLUMN updated_at TEXT")


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
    """创建告警；若同一视频源+同一类型已有未处理告警，则合并更新并累计次数。"""
    with _conn() as c:
        created = now_text()
        exist = c.execute(
            "SELECT * FROM alarms WHERE camera_id=? AND alarm_type=? AND status='unhandled' ORDER BY id DESC LIMIT 1",
            (camera_id, alarm_type),
        ).fetchone()
        if exist:
            count = int(exist["count"] or 1) + 1
            c.execute(
                "UPDATE alarms SET confidence=?, created_at=?, updated_at=?, count=? WHERE id=?",
                (round(confidence, 3), created, created, count, exist["id"]),
            )
            merged = dict(exist)
            merged.update(
                {
                    "confidence": round(confidence, 3),
                    "created_at": created,
                    "updated_at": created,
                    "count": count,
                }
            )
            return merged
        cur = c.execute(
            "INSERT INTO alarms(camera_id,camera_name,alarm_type,level,confidence,created_at,status,count,updated_at)"
            " VALUES(?,?,?,?,?,?,'unhandled',1,?)",
            (camera_id, camera_name, alarm_type, level, confidence, created, created),
        )
        return {
            "id": int(cur.lastrowid),
            "camera_id": camera_id,
            "camera_name": camera_name,
            "alarm_type": alarm_type,
            "level": level,
            "confidence": round(confidence, 3),
            "created_at": created,
            "updated_at": created,
            "count": 1,
            "status": "unhandled",
        }


def list_alarms(limit: int = 100) -> list[dict[str, Any]]:
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM alarms ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]


def ack_alarm(alarm_id: int) -> bool:
    with _conn() as c:
        cur = c.execute("UPDATE alarms SET status='handled' WHERE id=? AND status='unhandled'", (alarm_id,))
        return cur.rowcount > 0


def ack_alarm_group(camera_id: int, alarm_type: str) -> int:
    """把同一视频源、同一类型的所有未处理告警一次性标记为已处理，返回处理条数。"""
    with _conn() as c:
        cur = c.execute(
            "UPDATE alarms SET status='handled' WHERE camera_id=? AND alarm_type=? AND status='unhandled'",
            (camera_id, alarm_type),
        )
        return cur.rowcount


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
